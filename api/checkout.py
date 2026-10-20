import json
import math
import os
from http.server import BaseHTTPRequestHandler

# Display-frame checkout.
#
# The cart previously showed "your order has been placed" and went no further —
# no payment was ever taken. This endpoint is honest by construction: it only
# redirects to a Stripe Payment Link when STRIPE_PAYMENT_LINK is configured,
# and otherwise answers 501 with a clear message. No card data ever touches
# this function; Stripe hosts the payment page.
#
# A single Payment Link covers the whole catalogue. When more products go on
# sale, replace this with a Stripe Checkout session created per cart.

PAYMENT_LINK = os.environ.get('STRIPE_PAYMENT_LINK', '')

MAX_BODY_BYTES = 8192


def _clean(value, limit):
    return str(value or '').strip()[:limit]


def validate(payload):
    """Return (items, total, error). `items` is None when the payload is invalid."""
    if not isinstance(payload, dict):
        return None, None, 'Invalid JSON.'

    raw_items = payload.get('items')
    if not isinstance(raw_items, list) or not raw_items:
        return None, None, 'Cart is empty.'

    items = []
    total = 0.0
    for entry in raw_items[:20]:
        if not isinstance(entry, dict):
            continue
        name = _clean(entry.get('name'), 120)
        if not name:
            continue
        try:
            price = float(entry.get('price'))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price) or price <= 0 or price > 100000:
            continue
        items.append({'name': name, 'price': round(price, 2)})
        total += price

    if not items:
        return None, None, 'No purchasable items in cart.'

    return items, round(total, 2), None


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

        items, total, error = validate(payload)
        if error:
            self._json(400, {'error': error})
            return

        if not PAYMENT_LINK:
            # Deliberately not a 200: nothing was sold and nothing was charged.
            self._json(501, {
                'error': 'Online checkout is not switched on yet. Please use Design to Order and we will invoice you.',
                'total': total,
            })
            return

        self._json(200, {
            'checkoutUrl': PAYMENT_LINK,
            'total': total,
            'items': items,
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