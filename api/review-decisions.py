import hmac
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

"""Store Bluey outlier-review classifications for later application.

The review page is public evidence, not private data. This endpoint stores only
listing IDs, the user's decision values, and a submission time in the existing
Vercel KV (Upstash Redis) service. It never writes to the marketplace ledger;
Bluey Chief applies stored decisions in the next publication batch.
"""

QUEUE_KEY = "bluey:review-decisions:queue"
READ_TOKEN_ENV = "REVIEW_QUEUE_READ_TOKEN"
READ_TOKEN_HEADER = "X-Review-Read-Token"
DECISION_VALUES = {
    "recent-only",
    "also-in-value",
    "keep-out",
    "not-valid",
    "publish-recent",
    "publish-value",
    "keep-held",
    "keep-pending",
}
LISTING_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_BODY_BYTES = 128 * 1024
MAX_DECISIONS = 100
FORWARD_TIMEOUT = 6


def validate(payload):
    if not isinstance(payload, dict):
        return None, "Invalid JSON."
    if payload.get("kind") != "bluey-outlier-review":
        return None, "Missing bluey-outlier-review kind."
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        return None, "No decisions were submitted."
    if len(decisions) > MAX_DECISIONS:
        return None, "Too many decisions in one submission."

    cleaned = []
    for item in decisions:
        if not isinstance(item, dict):
            return None, "Each decision must be an object."
        listing_id = str(item.get("listing_id") or "").strip()
        decision = str(item.get("decision") or "").strip()
        if not LISTING_ID_RE.match(listing_id):
            return None, "A decision has an invalid listing ID."
        if decision not in DECISION_VALUES:
            return None, f"Invalid decision for listing {listing_id}."
        cleaned.append({"listing_id": listing_id, "decision": decision})

    record = {
        "kind": "bluey-outlier-review",
        "source": "blueyco.in/outlier-review",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "decisions": cleaned,
    }
    return record, None


def _rest_value(name):
    return (os.environ.get(name) or "").strip()


def deliver(record):
    url = _rest_value("KV_REST_API_URL") or _rest_value("UPSTASH_REDIS_REST_URL")
    token = _rest_value("KV_REST_API_TOKEN") or _rest_value("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        return False, "Decision storage is not configured."
    commands = [
        ["RPUSH", QUEUE_KEY, json.dumps(record, separators=(",", ":"))],
        ["EXPIRE", QUEUE_KEY, str(90 * 24 * 60 * 60)],
    ]
    body = json.dumps(commands, separators=(",", ":")).encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/pipeline",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=FORWARD_TIMEOUT) as response:
            data = json.load(response)
    except Exception as exc:  # keep transport details out of the public reply
        print(f"outlier review storage failed: {type(exc).__name__}")
        return False, "Decision storage is unavailable."
    if not isinstance(data, list) or any(
        isinstance(part, dict) and part.get("error") for part in data
    ):
        return False, "Decision storage rejected the submission."
    return True, None


def check_read_auth(presented):
    """True only when a read token is configured and matches exactly.

    Fail closed: missing configuration or any mismatch denies access.
    """
    expected = _rest_value(READ_TOKEN_ENV)
    if not expected or not presented:
        return False
    return hmac.compare_digest(str(presented), expected)


def read_queue():
    """Return (records, skipped, error) for every saved review submission.

    Records are returned oldest-first as stored. Malformed entries are
    skipped and counted, never served. Transport or storage failures
    return an error so callers fail closed.
    """
    url = _rest_value("KV_REST_API_URL") or _rest_value("UPSTASH_REDIS_REST_URL")
    token = _rest_value("KV_REST_API_TOKEN") or _rest_value("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        return None, 0, "Decision storage is not configured."
    body = json.dumps([["LRANGE", QUEUE_KEY, 0, -1]],
                      separators=(",", ":")).encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/pipeline",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=FORWARD_TIMEOUT) as response:
            data = json.load(response)
    except Exception as exc:  # keep transport details out of the reply
        print(f"outlier review read failed: {type(exc).__name__}")
        return None, 0, "Decision storage is unavailable."
    if not isinstance(data, list) or not data:
        return None, 0, "Decision storage rejected the read."
    result = data[0].get("result") if isinstance(data[0], dict) else None
    if not isinstance(result, list):
        return None, 0, "Decision storage rejected the read."
    records = []
    skipped = 0
    for item in result:
        try:
            record = json.loads(item)
        except (json.JSONDecodeError, ValueError, TypeError):
            skipped += 1
            continue
        if (not isinstance(record, dict)
                or record.get("kind") != "bluey-outlier-review"
                or not isinstance(record.get("decisions"), list)):
            skipped += 1
            continue
        records.append(record)
    return records, skipped, None

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._json(400, {"stored": False, "error": "Invalid request body."})
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"")
        except (json.JSONDecodeError, ValueError):
            self._json(400, {"stored": False, "error": "Invalid JSON."})
            return

        record, error = validate(payload)
        if error:
            self._json(400, {"stored": False, "error": error})
            return

        stored, detail = deliver(record)
        if stored:
            self._json(200, {"stored": True, "count": len(record["decisions"])})
        else:
            self._json(502, {"stored": False, "error": detail})

    def do_GET(self):
        if not check_read_auth(self.headers.get(READ_TOKEN_HEADER)):
            self._json(401, {"records": [], "error": "Unauthorized."})
            return
        records, skipped, error = read_queue()
        if error is not None:
            self._json(502, {"records": [], "error": error})
            return
        self._json(200, {"records": records, "skipped": skipped,
                        "count": len(records)})

    def _json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
