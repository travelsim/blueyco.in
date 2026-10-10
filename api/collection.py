# Pure Python stdlib — synced collection for signed-in collectors.
#
#   GET    /api/collection   → saved {collection, wishlist, swapOffer}
#   PUT    /api/collection   → replace it (coin ids only, validated)
#   DELETE /api/collection   → delete the saved copy and sign out
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _auth as A  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _session_store(self, write=False):
        """Return (session, store), or send the error response and return None."""
        if write and not A.same_origin(self.headers):
            self._json(403, {'error': 'Cross-site request refused.'})
            return None
        session = A.read_session(self.headers.get('Cookie'))
        if not session:
            self._json(401, {'error': 'Sign in to sync your collection.'})
            return None
        store = A.get_store()
        if store is None:
            self._json(503, {'error': 'Saved collections are not available yet.'})
            return None
        return session, store

    def do_GET(self):
        ctx = self._session_store()
        if ctx:
            try:
                self._json(200, A.load_collection(ctx[1], ctx[0]['uid']))
            except Exception as e:
                print(f'collection error: {type(e).__name__}')
                self._json(502, {'error': 'Saved collections are temporarily unavailable.'})

    def do_PUT(self):
        ctx = self._session_store(write=True)
        if not ctx:
            return
        try:
            length = int(self.headers.get('Content-Length') or 0)
            if length <= 0 or length > A.MAX_BODY_BYTES:
                raise ValueError
            payload = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._json(400, {'error': 'Invalid request.'})
            return
        data, error = A.clean_collection_data(payload.get('data') if isinstance(payload, dict) else None)
        if error:
            self._json(400, {'error': error})
            return
        try:
            self._json(200, {'updatedAt': A.save_collection(ctx[1], ctx[0]['uid'], data)})
        except Exception as e:
            print(f'collection error: {type(e).__name__}')
            self._json(502, {'error': 'Saved collections are temporarily unavailable.'})

    def do_DELETE(self):
        ctx = self._session_store(write=True)
        if not ctx:
            return
        try:
            ctx[1].delete(A.data_key(ctx[0]['uid']))
        except Exception as e:
            print(f'collection error: {type(e).__name__}')
            self._json(502, {'error': 'Could not delete saved data. Try again.'})
            return
        self._json(200, {'deleted': True}, cookie=A.session_cookie('', 0))

    def _json(self, status, payload, cookie=None):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(data)
