import json
import os
import re
import urllib.request
from http.server import BaseHTTPRequestHandler

# Custom frame ("Design to Order") lead capture.
#
# The form on the site used to fire an alert() and discard the submission, so
# every enquiry was lost. This endpoint validates the request and forwards it to
# LEAD_WEBHOOK_URL (Slack, Discord, Zapier, Make, a mail relay — anything that
# accepts a JSON POST). It reports honestly whether the lead was delivered:
# without a webhook configured it answers 202 with `delivered: false` rather
# than pretending the request was received.
#
# No lead content is logged and nothing is persisted to disk — serverless
# instances are ephemeral and must not accumulate customer data.

WEBHOOK_URL = os.environ.get('LEAD_WEBHOOK_URL', '')
FORWARD_TIMEOUT = 6

MAX_BODY_BYTES = 8192
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$')


def _clean(value, limit):
    value = str(value or '').strip()
    return value[:limit]


def validate(payload):
    """Return (fields, error). `fields` is None when the payload is invalid."""
    if not isinstance(payload, dict):
        return None, 'Invalid JSON.'

    fields = {
        'name': _clean(payload.get('name'), 120),
        'email': _clean(payload.get('email'), 200).lower(),
        'coin': _clean(payload.get('coin'), 200),
        'notes': _clean(payload.get('notes'), 2000),
    }

    if not fields['name']:
        return None, 'Name is required.'
    if not EMAIL_RE.match(fields['email']):
        return None, 'A valid email address is required.'
    if not fields['coin']:
        return None, 'Which coin or set is the frame for?'

    return fields, None


def deliver(fields):
    """Forward the lead. Returns (delivered, detail)."""
    if not WEBHOOK_URL:
        return False, 'No LEAD_WEBHOOK_URL is configured.'
    body = json.dumps({
        'text': (
            f"New Bluey custom frame request\n"
            f"Name: {fields['name']}\n"
            f"Email: {fields['email']}\n"
            f"Coin: {fields['coin']}"
            + (f"\nNotes: {fields['notes']}" if fields['notes'] else '')
        ),
        'name': fields['name'],
        'email': fields['email'],
        'coin': fields['coin'],
        'notes': fields['notes'],
        'source': 'blueyco.in/design-to-order',
    }).encode()
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=FORWARD_TIMEOUT) as r:
            ok = 200 <= r.status < 300
            return ok, None if ok else f'Webhook returned HTTP {r.status}.'
    except Exception as e:
        return False, f'Webhook delivery failed: {e}'


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._json(400, {'error': 'Invalid request body.'})
            return
        try:
            payload = json.loads(self.rfile.read(length) or b'')
        except (json.JSONDecodeError, ValueError):
            self._json(400, {'error': 'Invalid JSON.'})
            return

        fields, error = validate(payload)
        if error:
            self._json(400, {'error': error})
            return

        delivered, detail = deliver(fields)
        if delivered:
            self._json(200, {'delivered': True, 'message': 'Request received.'})
        else:
            # The lead could not be forwarded. Say so, and log only the reason —
            # never the customer's details.
            print(f"lead not delivered: {detail}")
            self._json(202, {
                'delivered': False,
                'error': 'Custom frame requests are not being delivered yet. Please email us instead.',
            })

    def do_GET(self):
        self._json(405, {'error': 'Use POST with a JSON body.'})

    def _json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)