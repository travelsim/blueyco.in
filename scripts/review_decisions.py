"""Reviewer decisions: fetch, collapse, record, and apply.

Reads saved outlier-review decisions (authenticated GET API when
REVIEW_QUEUE_READ_TOKEN is set, otherwise the KV REST queue when
KV_REST_API_URL/KV_REST_API_TOKEN are set) and fails closed when neither
credential is available. Latest submission wins per listing_id. Decisions
are recorded durably in the Melbourne ledger (review_decisions table)
before any publication step consumes them.

Disposition mapping (fail closed: unmapped values never publish):
  recent-only   -> published, excluded from Market Value medians
  also-in-value -> published, included in both Recent Sales and Market Value
  keep-held     -> held, hidden everywhere
  not-valid     -> excluded, hidden everywhere
  keep-pending  -> queued for reviewer mapping, never published
  keep-out      -> queued hidden (offered 2026-11-24 with no legend
                   definition; intent unsettled, fail closed)
  unknown       -> queued hidden (fail closed, reported)
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import melbourne_drift as drift

REVIEW_API_BASE = os.environ.get("REVIEW_API_BASE",
                                 "https://blueyco.in").rstrip("/")
FETCH_TIMEOUT = 15

# action, value_eligible, manifest reason
DISPOSITIONS = {
    "recent-only": ("published", False, "reviewer recent-only"),
    "also-in-value": ("published", True, "reviewer also-in-value"),
    "keep-held": ("held", True, "reviewer keep-held"),
    "not-valid": ("excluded", True, "reviewer not-valid"),
    "keep-pending": ("pending-review", True, "reviewer keep-pending"),
    "keep-out": ("pending-review", True,
                 "reviewer keep-out (unmapped at decision time; held pending, fail closed)"),
}


class DecisionFetchError(RuntimeError):
    """Raised when no authenticated decisions source is available."""


def _env(name):
    return (os.environ.get(name) or "").strip()


def fetch_records():
    """Return saved review records, oldest first. Fail closed without auth.

    Prefers the authenticated GET API when REVIEW_QUEUE_READ_TOKEN is set;
    otherwise reads the KV REST queue directly when KV_REST_API_URL and
    KV_REST_API_TOKEN are set. Raises DecisionFetchError when neither
    credential is available or the read fails.
    """
    token = _env("REVIEW_QUEUE_READ_TOKEN")
    if token:
        return _fetch_via_api(token)
    url = _env("KV_REST_API_URL") or _env("UPSTASH_REDIS_REST_URL")
    kv_token = _env("KV_REST_API_TOKEN") or _env("UPSTASH_REDIS_REST_TOKEN")
    if url and kv_token:
        return _fetch_via_kv(url, kv_token)
    raise DecisionFetchError(
        "no review-decisions credential: set REVIEW_QUEUE_READ_TOKEN "
        "or KV_REST_API_URL/KV_REST_API_TOKEN")


def _fetch_via_api(token):
    req = urllib.request.Request(
        REVIEW_API_BASE + "/api/review-decisions",
        headers={"X-Review-Read-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            data = json.load(resp)
    except Exception as exc:
        raise DecisionFetchError(
            "review-decisions read failed: %s" % type(exc).__name__)
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise DecisionFetchError("review-decisions read rejected")
    return data["records"]


def _fetch_via_kv(url, token):
    body = json.dumps([["LRANGE", "bluey:review-decisions:queue", 0, -1]],
                      separators=(",", ":")).encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/pipeline", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            data = json.load(resp)
    except Exception as exc:
        raise DecisionFetchError(
            "review-decisions read failed: %s" % type(exc).__name__)
    if not isinstance(data, list) or not data:
        raise DecisionFetchError("review-decisions read rejected")
    result = data[0].get("result") if isinstance(data[0], dict) else None
    if not isinstance(result, list):
        raise DecisionFetchError("review-decisions read rejected")
    records = []
    for item in result:
        try:
            record = json.loads(item)
        except (ValueError, TypeError):
            continue
        if (isinstance(record, dict)
                and record.get("kind") == "bluey-outlier-review"
                and isinstance(record.get("decisions"), list)):
            records.append(record)
    return records


def collapse_records(records):
    """Latest submission wins per listing_id.

    Returns ({listing_id: (decision, submitted_at)}, stats dict).
    """
    decided = {}
    stats = {"records": 0, "duplicate_listings": 0}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        stats["records"] += 1
        submitted = str(record.get("submitted_at") or "")
        for item in record.get("decisions") or []:
            if not isinstance(item, dict):
                continue
            lid = str(item.get("listing_id") or "")
            decision = str(item.get("decision") or "")
            if not lid or not decision:
                continue
            if lid in decided:
                stats["duplicate_listings"] += 1
                if submitted < decided[lid][1]:
                    continue
            decided[lid] = (decision, submitted)
    stats["unique_listings"] = len(decided)
    stats["by_decision"] = {}
    for decision, _ in decided.values():
        stats["by_decision"][decision] = stats["by_decision"].get(decision, 0) + 1
    return decided, stats


def disposition_for(decision):
    """Map a reviewer decision to (action, value_eligible, reason).

    Unknown values are excluded: fail closed, reported via the reason.
    """
    if decision in DISPOSITIONS:
        return DISPOSITIONS[decision]
    return ("pending-review", True,
            "reviewer decision %r unmapped (held pending, fail closed)"
            % (decision,))


_DDL = """CREATE TABLE IF NOT EXISTS review_decisions (
  listing_id TEXT PRIMARY KEY,
  decision TEXT NOT NULL,
  submitted_at TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'bluey-outlier-review',
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);"""


def _quote(text):
    return "'" + str(text or "").replace("'", "''") + "'"


def record_melbourne(decided, source="bluey-outlier-review"):
    """Durably record collapsed decisions in the Melbourne ledger.

    Upserts into review_decisions; never downgrades a stored decision with
    an older submission. Returns the number of rows written. Raises on
    transport failure so callers fail closed.
    """
    drift._ssh_psql(_DDL)
    written = 0
    for lid, (decision, submitted) in sorted(decided.items()):
        sql = ("INSERT INTO review_decisions "
               "(listing_id, decision, submitted_at, source) VALUES (%s, %s, %s, %s) "
               "ON CONFLICT (listing_id) DO UPDATE SET "
               "decision=EXCLUDED.decision, submitted_at=EXCLUDED.submitted_at, "
               "source=EXCLUDED.source, recorded_at=now() "
               "WHERE review_decisions.submitted_at IS NULL "
               "OR EXCLUDED.submitted_at >= review_decisions.submitted_at;" % (
                   _quote(lid), _quote(decision),
                   _quote(submitted), _quote(source)))
        out = drift._ssh_psql(sql)
        if "INSERT" in out or "UPDATE 1" in out:
            written += 1
    return written


def fetch_and_record(source="bluey-outlier-review"):
    """Fetch saved decisions, collapse latest-wins, record to Melbourne.

    Returns (decided, stats, recorded). Raises DecisionFetchError when no
    authenticated source is available, before any publication step runs.
    """
    records = fetch_records()
    decided, stats = collapse_records(records)
    recorded = record_melbourne(decided, source=source)
    stats["recorded"] = recorded
    return decided, stats, recorded
