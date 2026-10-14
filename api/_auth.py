# Pure Python stdlib — shared by api/auth.py and api/collection.py.
#
# Optional sign-in so collectors can keep their collection across devices.
# The site stays fully usable signed out (the collection lives in localStorage);
# signing in adds sync, nothing is gated behind it.
#
# What is stored: a one-way hash of the verified email address as the account
# key, and the collection JSON (coin ids only). No email, name or photo is
# persisted. Sessions are signed HttpOnly cookies; magic-link tokens are
# single use and expire after 10 minutes.
#
# Everything is switched off — and reports itself off — until its secrets are
# configured, so shipping this code changes nothing for visitors by itself.
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage

SESSION_COOKIE = '__Secure-bluey.session-token'
SESSION_TTL = 30 * 24 * 3600
MAGIC_TTL = 600
MAX_BODY_BYTES = 32768
EMAIL_RE = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$')
COIN_ID_RE = re.compile(r'^[a-z0-9_]{1,64}$')
DATA_KEYS = ('collection', 'wishlist', 'swapOffer')
MAX_ENTRIES = 300
GOOGLE_ISSUERS = {'accounts.google.com', 'https://accounts.google.com'}


def cfg(name, default=''):
    return (os.environ.get(name) or default).strip()


def session_secret():
    return cfg('SESSION_SECRET')


def site_url():
    return cfg('SITE_URL', 'https://blueyco.in').rstrip('/')


def kv_available():
    return bool(cfg('KV_REST_API_URL') and cfg('KV_REST_API_TOKEN')) or cfg('AUTH_STORE') == 'memory'


def google_enabled():
    return bool(cfg('GOOGLE_CLIENT_ID') and session_secret() and kv_available())


def smtp_configured():
    return all(cfg(n) for n in ('SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_FROM'))


def magic_enabled():
    return bool(smtp_configured() and session_secret() and kv_available())


def auth_enabled():
    return google_enabled() or magic_enabled()


# ── Store ────────────────────────────────────────────────────────────────────
class MemoryStore:
    """Process-local store for tests and local development only."""

    def __init__(self):
        self.data = {}

    def _live(self, key):
        item = self.data.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and expires <= time.time():
            del self.data[key]
            return None
        return value

    def get(self, key):
        return self._live(key)

    def set(self, key, value, ttl=None):
        self.data[key] = (value, time.time() + ttl if ttl else None)

    def getdel(self, key):
        value = self._live(key)
        self.data.pop(key, None)
        return value

    def delete(self, key):
        self.data.pop(key, None)

    def incr(self, key, ttl):
        value = self._live(key)
        count = int(value or 0) + 1
        expires = self.data[key][1] if key in self.data else time.time() + ttl
        self.data[key] = (str(count), expires)
        return count


class RestStore:
    """Upstash Redis over its REST API (the Vercel KV integration)."""

    def __init__(self, url, token, timeout=5):
        self.url, self.token, self.timeout = url.rstrip('/'), token, timeout

    def _cmd(self, *args):
        req = urllib.request.Request(
            self.url,
            data=json.dumps([str(a) for a in args]).encode(),
            headers={'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            body = json.loads(r.read())
        if 'error' in body:
            raise RuntimeError('store error')
        return body.get('result')

    def get(self, key):
        return self._cmd('GET', key)

    def set(self, key, value, ttl=None):
        if ttl:
            self._cmd('SET', key, value, 'EX', int(ttl))
        else:
            self._cmd('SET', key, value)

    def getdel(self, key):
        return self._cmd('GETDEL', key)

    def delete(self, key):
        self._cmd('DEL', key)

    def incr(self, key, ttl):
        count = int(self._cmd('INCR', key))
        if count == 1:
            self._cmd('EXPIRE', key, int(ttl))
        return count


_memory_store = MemoryStore()


def get_store():
    if cfg('KV_REST_API_URL') and cfg('KV_REST_API_TOKEN'):
        return RestStore(cfg('KV_REST_API_URL'), cfg('KV_REST_API_TOKEN'))
    if cfg('AUTH_STORE') == 'memory':
        return _memory_store
    return None


# ── Sessions ─────────────────────────────────────────────────────────────────
def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _unb64(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _sign(body):
    return _b64(hmac.new(session_secret().encode(), body.encode(), hashlib.sha256).digest())


def user_id(email):
    """Stable account key from a verified email; the address itself is not stored."""
    return hashlib.sha256(('bluey-user:' + email.strip().lower()).encode()).hexdigest()[:40]


def mask_email(email):
    local, _, domain = email.strip().lower().partition('@')
    return (local[:1] + '***@' + domain) if local else domain


def make_session(email, now=None):
    now = int(now if now is not None else time.time())
    payload = {'uid': user_id(email), 'em': mask_email(email), 'exp': now + SESSION_TTL}
    body = _b64(json.dumps(payload, separators=(',', ':')).encode())
    return body + '.' + _sign(body)


def read_session(cookie_header, now=None):
    """Return the session payload from a Cookie header, or None."""
    if not session_secret() or not cookie_header:
        return None
    token = None
    for part in cookie_header.split(';'):
        name, _, value = part.strip().partition('=')
        if name == SESSION_COOKIE:
            token = value
    if not token or '.' not in token:
        return None
    body, _, sig = token.partition('.')
    if not hmac.compare_digest(sig, _sign(body)):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get('exp', 0) <= (now if now is not None else time.time()):
        return None
    if not re.fullmatch(r'[0-9a-f]{40}', str(payload.get('uid', ''))):
        return None
    return payload


def session_cookie(value, max_age=SESSION_TTL):
    return f'{SESSION_COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; Secure; SameSite=Lax'


# ── Google ───────────────────────────────────────────────────────────────────
def verify_google_credential(credential, fetch=None):
    """Validate a Google ID token via Google's tokeninfo endpoint.

    Returns the verified lowercase email, or None. The audience must be our
    client id, the issuer Google, the token unexpired and the email verified.
    """
    client_id = cfg('GOOGLE_CLIENT_ID')
    if not client_id or not isinstance(credential, str) or not (20 <= len(credential) <= 4096):
        return None
    if fetch is None:
        def fetch(token):
            url = 'https://oauth2.googleapis.com/tokeninfo?' + urllib.parse.urlencode({'id_token': token})
            with urllib.request.urlopen(url, timeout=6) as r:
                return json.loads(r.read())
    try:
        info = fetch(credential)
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    try:
        expired = int(info.get('exp', 0)) <= time.time()
    except (TypeError, ValueError):
        return None
    email = str(info.get('email') or '').strip().lower()
    if (info.get('aud') != client_id or info.get('iss') not in GOOGLE_ISSUERS or expired
            or str(info.get('email_verified')).lower() != 'true' or not EMAIL_RE.match(email)):
        return None
    return email


# ── Magic link ───────────────────────────────────────────────────────────────
def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def rate_limited(store, email, ip):
    """Count a magic-link request. True when this address or IP is over its limit."""
    over_email = store.incr('rl:e:' + _hash(email), 3600) > 3
    over_ip = store.incr('rl:i:' + _hash(ip or 'unknown'), 3600) > 10
    return over_email or over_ip


def create_magic_token(store, email):
    token = secrets.token_urlsafe(32)
    store.set('ml:' + _hash(token), email, MAGIC_TTL)
    return token


def consume_magic_token(store, token):
    """Single use: the token is deleted as it is read. Returns the email or None."""
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,100}', token):
        return None
    email = store.getdel('ml:' + _hash(token))
    return email if email and EMAIL_RE.match(email) else None


def build_magic_message(email, token):
    link = f'{site_url()}/#login={token}'
    msg = EmailMessage()
    msg['Subject'] = 'Your Blueycoin sign-in link'
    msg['From'] = f'Blueycoin <{cfg("SMTP_FROM")}>'
    msg['To'] = email
    msg.set_content(
        'Use this link to sign in to Blueycoin and sync your collection:\n\n'
        f'{link}\n\n'
        'It works once and expires in 10 minutes. If you did not ask for it, '
        'ignore this email — nothing happens unless the link is opened.\n'
    )
    return msg


def send_magic_email(email, token, smtp_factory=None):
    msg = build_magic_message(email, token)
    host, port = cfg('SMTP_HOST'), int(cfg('SMTP_PORT', '465'))
    if smtp_factory is None:
        smtp_factory = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with smtp_factory(host, port, timeout=8) as smtp:
        if port != 465 and hasattr(smtp, 'starttls'):
            smtp.starttls()
        smtp.login(cfg('SMTP_USER'), cfg('SMTP_PASSWORD'))
        smtp.send_message(msg)


# ── Collection data ──────────────────────────────────────────────────────────
def clean_collection_data(payload):
    """Validate client data. Returns (clean, error); only truthy coin ids are kept."""
    if not isinstance(payload, dict):
        return None, 'Invalid data.'
    clean = {}
    for key in DATA_KEYS:
        section = payload.get(key, {})
        if not isinstance(section, dict) or len(section) > MAX_ENTRIES * 2:
            return None, 'Invalid data.'
        ids = sorted(k for k, v in section.items() if v is True and COIN_ID_RE.match(str(k)))
        if len(ids) > MAX_ENTRIES:
            return None, 'Too many entries.'
        clean[key] = {i: True for i in ids}
    return clean, None


def data_key(uid):
    return 'col:' + uid


def load_collection(store, uid):
    raw = store.get(data_key(uid))
    if not raw:
        return {'data': {k: {} for k in DATA_KEYS}, 'updatedAt': 0}
    try:
        record = json.loads(raw)
        data, _ = clean_collection_data(record.get('data'))
        return {'data': data or {k: {} for k in DATA_KEYS}, 'updatedAt': int(record.get('updatedAt', 0))}
    except (ValueError, TypeError, AttributeError):
        return {'data': {k: {} for k in DATA_KEYS}, 'updatedAt': 0}


def save_collection(store, uid, data, now=None):
    record = {'data': data, 'updatedAt': int(now if now is not None else time.time())}
    store.set(data_key(uid), json.dumps(record, separators=(',', ':')))
    return record['updatedAt']


# ── HTTP helpers ─────────────────────────────────────────────────────────────
def same_origin(headers):
    """Reject cross-site POSTs: Origin (when sent) must match the Host."""
    origin = headers.get('Origin')
    if not origin:
        return True
    host = headers.get('X-Forwarded-Host') or headers.get('Host') or ''
    return urllib.parse.urlsplit(origin).netloc == host.split(',')[0].strip()


def client_ip(headers):
    """Best available client address for rate limiting.

    Vercel overwrites X-Forwarded-For with the real public IP to prevent
    spoofing (https://vercel.com/docs/headers/request-headers), and sets
    X-Vercel-Forwarded-For identically — that one survives a proxy put in front
    of Vercel. Prefer it, then fall back so plain local servers still rate limit.
    """
    for name in ('X-Vercel-Forwarded-For', 'X-Forwarded-For', 'X-Real-IP'):
        value = (headers.get(name) or '').strip()
        if value:
            return value.split(',')[0].strip()
    return ''
