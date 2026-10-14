# Pure Python stdlib — sign-in endpoint. See api/_auth.py for the design.
#
#   GET  /api/auth                      → who is signed in + which methods are on
#   POST /api/auth {action:'google'}    → verify a Google ID token, start a session
#   POST /api/auth {action:'magic_request', email}
#                                       → email a single-use sign-in link
#   POST /api/auth {action:'magic_verify', token}
#                                       → exchange the link token for a session
#   POST /api/auth {action:'logout'}    → clear the session
#
# The emailed link points at /#login=<token> and is exchanged by a POST from the
# page. A mail scanner that merely opens the link therefore cannot burn the token.
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _auth as A  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        session = A.read_session(self.headers.get('Cookie'))
        self._json(200, {
            'google': A.google_enabled(),
            'googleClientId': A.cfg('GOOGLE_CLIENT_ID') if A.google_enabled() else '',
            'magic': A.magic_enabled(),
            'user': {'email': session['em']} if session else None,
        })

    def do_POST(self):
        if not A.same_origin(self.headers):
            self._json(403, {'error': 'Cross-site request refused.'})
            return
        payload = self._body()
        if payload is None:
            self._json(400, {'error': 'Invalid request.'})
            return
        action = payload.get('action')
        if action == 'logout':
            self._json(200, {'ok': True}, cookie=A.session_cookie('', 0))
            return
        if not A.auth_enabled():
            self._json(503, {'error': 'Sign-in is not available yet.'})
            return
        try:
            if action == 'google':
                self._google(payload)
            elif action == 'magic_request':
                self._magic_request(payload)
            elif action == 'magic_verify':
                self._magic_verify(payload)
            else:
                self._json(400, {'error': 'Unknown action.'})
        except Exception as e:  # store/SMTP failures must not leak details
            print(f'auth error: {type(e).__name__}')
            self._json(502, {'error': 'Sign-in is temporarily unavailable.'})

    def _google(self, payload):
        if not A.google_enabled():
            self._json(503, {'error': 'Google sign-in is not available yet.'})
            return
        email = A.verify_google_credential(payload.get('credential'))
        if not email:
            self._json(401, {'error': 'Google sign-in could not be verified.'})
            return
        self._signed_in(email)

    def _magic_request(self, payload):
        if not A.magic_enabled():
            self._json(503, {'error': 'Email sign-in is not available yet.'})
            return
        email = str(payload.get('email') or '').strip().lower()
        if not A.EMAIL_RE.match(email):
            self._json(400, {'error': 'Enter a valid email address.'})
            return
        store = A.get_store()
        if A.rate_limited(store, email, A.client_ip(self.headers)):
            self._json(429, {'error': 'Too many sign-in emails. Try again later.'})
            return
        A.send_magic_email(email, A.create_magic_token(store, email))
        self._json(200, {'sent': True, 'message': 'Check your email for a sign-in link. It works once and expires in 10 minutes.'})

    def _magic_verify(self, payload):
        if not A.magic_enabled():
            self._json(503, {'error': 'Email sign-in is not available yet.'})
            return
        email = A.consume_magic_token(A.get_store(), payload.get('token'))
        if not email:
            self._json(401, {'error': 'That sign-in link has expired or was already used.'})
            return
        self._signed_in(email)

    def _signed_in(self, email):
        self._json(200, {'user': {'email': A.mask_email(email)}}, cookie=A.session_cookie(A.make_session(email)))

    def _body(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return None
        if length <= 0 or length > A.MAX_BODY_BYTES:
            return None
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

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
