import http.client
import importlib.util
import json
import os
import sys
import threading
import time
import unittest
from http.server import HTTPServer
from unittest import mock

API = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'api')
sys.path.insert(0, API)
import _auth as A  # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location('api_' + name, os.path.join(API, name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUTH_API = _load('auth')
COLLECTION_API = _load('collection')

ENV = {
    'SESSION_SECRET': 'test-secret-value-0123456789',
    'AUTH_STORE': 'memory',
    'GOOGLE_CLIENT_ID': 'client-123.apps.googleusercontent.com',
    'SMTP_HOST': 'smtp.example.test',
    'SMTP_USER': 'login@example.test',
    'SMTP_PASSWORD': 'not-a-real-password',
    'SMTP_FROM': 'login@example.test',
}


class SessionTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_session_round_trip_keeps_only_hash_and_masked_email(self):
        cookie = A.SESSION_COOKIE + '=' + A.make_session('Jane.Doe@Example.com')
        payload = A.read_session(cookie)
        self.assertEqual(payload['uid'], A.user_id('jane.doe@example.com'))
        self.assertEqual(payload['em'], 'j***@example.com')
        self.assertNotIn('jane.doe', json.dumps(payload).lower())

    def test_tampered_expired_and_unsigned_sessions_are_rejected(self):
        token = A.make_session('a@example.com')
        body, sig = token.split('.')
        self.assertIsNone(A.read_session(f'{A.SESSION_COOKIE}={body}.{sig[:-2]}xx'))
        self.assertIsNone(A.read_session(f'{A.SESSION_COOKIE}=garbage'))
        self.assertIsNone(A.read_session(None))
        old = A.make_session('a@example.com', now=time.time() - A.SESSION_TTL - 10)
        self.assertIsNone(A.read_session(f'{A.SESSION_COOKIE}={old}'))
        with mock.patch.dict(os.environ, {'SESSION_SECRET': 'a-different-secret'}):
            self.assertIsNone(A.read_session(f'{A.SESSION_COOKIE}={token}'))

    def test_cookie_is_httponly_secure_samesite(self):
        cookie = A.session_cookie('x')
        for flag in ('HttpOnly', 'Secure', 'SameSite=Lax'):
            self.assertIn(flag, cookie)

    def test_nothing_is_enabled_without_secrets(self):
        with mock.patch.dict(os.environ, {'SESSION_SECRET': '', 'GOOGLE_CLIENT_ID': ''}):
            self.assertFalse(A.google_enabled())
            self.assertFalse(A.magic_enabled())
            self.assertFalse(A.auth_enabled())
            self.assertIsNone(A.read_session(A.SESSION_COOKIE + '=a.b'))


class GoogleTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.good = {
            'aud': ENV['GOOGLE_CLIENT_ID'], 'iss': 'https://accounts.google.com',
            'exp': str(int(time.time()) + 600), 'email': 'Jane@Example.com', 'email_verified': 'true',
        }

    def verify(self, **changes):
        info = {**self.good, **changes}
        return A.verify_google_credential('x' * 40, fetch=lambda token: info)

    def test_valid_token_returns_lowercase_email(self):
        self.assertEqual(self.verify(), 'jane@example.com')
        self.assertEqual(self.verify(iss='accounts.google.com'), 'jane@example.com')

    def test_wrong_audience_issuer_expiry_or_unverified_email_is_rejected(self):
        self.assertIsNone(self.verify(aud='someone-elses-client'))
        self.assertIsNone(self.verify(iss='https://evil.example'))
        self.assertIsNone(self.verify(exp=str(int(time.time()) - 5)))
        self.assertIsNone(self.verify(email_verified='false'))
        self.assertIsNone(self.verify(email='not-an-email'))

    def test_fetch_failure_and_bad_input_are_rejected(self):
        def boom(token):
            raise OSError('network')
        self.assertIsNone(A.verify_google_credential('x' * 40, fetch=boom))
        self.assertIsNone(A.verify_google_credential('short', fetch=lambda t: self.good))
        self.assertIsNone(A.verify_google_credential(None, fetch=lambda t: self.good))


class MagicLinkTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = A.MemoryStore()

    def test_token_is_single_use(self):
        token = A.create_magic_token(self.store, 'a@example.com')
        self.assertEqual(A.consume_magic_token(self.store, token), 'a@example.com')
        self.assertIsNone(A.consume_magic_token(self.store, token))

    def test_expired_and_malformed_tokens_are_rejected(self):
        token = A.create_magic_token(self.store, 'a@example.com')
        with mock.patch('time.time', return_value=time.time() + A.MAGIC_TTL + 5):
            self.assertIsNone(A.consume_magic_token(self.store, token))
        for bad in (None, '', 'short', 'x' * 200, 'has spaces ' * 5):
            self.assertIsNone(A.consume_magic_token(self.store, bad))

    def test_raw_token_is_never_the_storage_key(self):
        token = A.create_magic_token(self.store, 'a@example.com')
        self.assertFalse(any(token in key for key in self.store.data))

    def test_rate_limits_per_address_and_per_ip(self):
        results = [A.rate_limited(self.store, 'a@example.com', '1.1.1.1') for _ in range(4)]
        self.assertEqual(results, [False, False, False, True])
        store = A.MemoryStore()
        hits = [A.rate_limited(store, f'u{i}@example.com', '2.2.2.2') for i in range(11)]
        self.assertEqual(hits[:10], [False] * 10)
        self.assertTrue(hits[10])

    def test_email_links_to_a_fragment_not_a_query_string(self):
        msg = A.build_magic_message('a@example.com', 'T' * 43)
        body = msg.get_content()
        self.assertIn('https://blueyco.in/#login=' + 'T' * 43, body)
        self.assertNotIn('?', body.split('#login=')[0].splitlines()[-1])
        self.assertEqual(msg['To'], 'a@example.com')
        self.assertIn('login@example.test', msg['From'])

    def test_smtp_sends_over_ssl_with_login(self):
        sent = {}

        class FakeSMTP:
            def __init__(self, host, port, timeout):
                sent.update(host=host, port=port)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def login(self, user, password):
                sent['login'] = user

            def send_message(self, msg):
                sent['to'] = msg['To']

        A.send_magic_email('a@example.com', 'T' * 43, smtp_factory=FakeSMTP)
        self.assertEqual(sent, {'host': 'smtp.example.test', 'port': 465, 'login': 'login@example.test', 'to': 'a@example.com'})


class CollectionDataTests(unittest.TestCase):
    def test_only_truthy_valid_coin_ids_are_kept(self):
        clean, error = A.clean_collection_data({
            'collection': {'s1_bluey': True, 'gone': False, 'BAD ID': True, 'x' * 80: True},
            'wishlist': {'s4_cricket_unc': True},
        })
        self.assertIsNone(error)
        self.assertEqual(clean, {'collection': {'s1_bluey': 1}, 'wishlist': {'s4_cricket_unc': True}, 'swapOffer': {}})

    def test_collection_quantities_accepted_clamped_and_rejected(self):
        clean, error = A.clean_collection_data({
            'collection': {'one': 1, 'many': 3, 'huge': 150, 'zero': 0,
                           'neg': -2, 'half': 2.5, 'text': '3', 'off': False,
                           'nothing': None, 'BAD ID': 2},
            'wishlist': {'want': 2, 'really': True},
        })
        self.assertIsNone(error)
        self.assertEqual(clean['collection'], {'huge': 99, 'many': 3, 'one': 1})
        self.assertEqual(clean['wishlist'], {'really': True})

    def test_rejects_wrong_shapes_and_oversize(self):
        for bad in (None, [], 'x', {'collection': []}, {'collection': {f'c{i}': True for i in range(700)}}):
            self.assertIsNotNone(A.clean_collection_data(bad)[1])

    def test_origin_check(self):
        self.assertTrue(A.same_origin({'Host': 'blueyco.in'}))
        self.assertTrue(A.same_origin({'Host': 'blueyco.in', 'Origin': 'https://blueyco.in'}))
        self.assertFalse(A.same_origin({'Host': 'blueyco.in', 'Origin': 'https://evil.example'}))

    def test_client_ip_prefers_the_vercel_header(self):
        # A proxy in front of Vercel can rewrite x-forwarded-for; the vercel
        # header survives it, so rate limiting must not key on the spoofable one.
        self.assertEqual(A.client_ip({'X-Vercel-Forwarded-For': '203.0.113.7',
                                      'X-Forwarded-For': '9.9.9.9'}), '203.0.113.7')
        self.assertEqual(A.client_ip({'X-Forwarded-For': '9.9.9.9, 203.0.113.7'}), '9.9.9.9')
        self.assertEqual(A.client_ip({'X-Real-IP': '198.51.100.4'}), '198.51.100.4')
        self.assertEqual(A.client_ip({}), '')


class HttpFlowTests(unittest.TestCase):
    """Drive the real handlers over HTTP with the in-memory store."""

    @classmethod
    def setUpClass(cls):
        cls.servers = []
        for module in (AUTH_API, COLLECTION_API):
            server = HTTPServer(('127.0.0.1', 0), module.handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            cls.servers.append(server)
        cls.auth_port, cls.col_port = (s.server_address[1] for s in cls.servers)

    @classmethod
    def tearDownClass(cls):
        for server in cls.servers:
            server.shutdown()

    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        A._memory_store.data.clear()
        self.emails = []
        sender = mock.patch.object(A, 'send_magic_email', lambda email, token: self.emails.append((email, token)))
        sender.start()
        self.addCleanup(sender.stop)

    def call(self, port, method, body=None, cookie=None, origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        headers = {'Content-Type': 'application/json'}
        if cookie:
            headers['Cookie'] = cookie
        if origin:
            headers['Origin'] = origin
        conn.request(method, '/', body=json.dumps(body) if body is not None else None, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read() or b'{}')
        set_cookie = resp.getheader('Set-Cookie')
        conn.close()
        return resp.status, data, set_cookie

    def sign_in(self, email='jane@example.com'):
        self.call(self.auth_port, 'POST', {'action': 'magic_request', 'email': email})
        token = self.emails[-1][1]
        status, data, set_cookie = self.call(self.auth_port, 'POST', {'action': 'magic_verify', 'token': token})
        self.assertEqual(status, 200)
        return set_cookie.split(';')[0]

    def test_config_reports_methods_and_no_user_when_signed_out(self):
        status, data, _ = self.call(self.auth_port, 'GET')
        self.assertEqual((status, data['google'], data['magic'], data['user']), (200, True, True, None))
        self.assertEqual(data['googleClientId'], ENV['GOOGLE_CLIENT_ID'])

    def test_disabled_when_unconfigured(self):
        with mock.patch.dict(os.environ, {'SESSION_SECRET': ''}):
            status, data, _ = self.call(self.auth_port, 'GET')
            self.assertEqual((data['google'], data['magic'], data['googleClientId']), (False, False, ''))
            status, data, _ = self.call(self.auth_port, 'POST', {'action': 'google', 'credential': 'x' * 40})
            self.assertEqual(status, 503)

    def test_magic_link_sign_in_sync_and_delete(self):
        cookie = self.sign_in()
        self.assertEqual(self.call(self.col_port, 'GET', cookie=cookie)[0], 200)
        self.assertEqual(self.call(self.col_port, 'GET', cookie=cookie)[1]['data']['collection'], {})
        status, _, _ = self.call(self.col_port, 'PUT', {'data': {'collection': {'s1_bluey': True}}}, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(self.call(self.col_port, 'GET', cookie=cookie)[1]['data']['collection'], {'s1_bluey': True})
        # Same person on another device sees the same data.
        other = self.sign_in('JANE@example.com')
        self.assertEqual(self.call(self.col_port, 'GET', cookie=other)[1]['data']['collection'], {'s1_bluey': True})
        status, _, cleared = self.call(self.col_port, 'DELETE', cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn('Max-Age=0', cleared)
        self.assertEqual(self.call(self.col_port, 'GET', cookie=other)[1]['data']['collection'], {})

    def test_link_cannot_be_replayed(self):
        self.call(self.auth_port, 'POST', {'action': 'magic_request', 'email': 'a@example.com'})
        token = self.emails[-1][1]
        first = self.call(self.auth_port, 'POST', {'action': 'magic_verify', 'token': token})
        second = self.call(self.auth_port, 'POST', {'action': 'magic_verify', 'token': token})
        self.assertEqual((first[0], second[0]), (200, 401))

    def test_signed_out_and_forged_requests_are_refused(self):
        self.assertEqual(self.call(self.col_port, 'GET')[0], 401)
        self.assertEqual(self.call(self.col_port, 'PUT', {'data': {}}, cookie=A.SESSION_COOKIE + '=forged.sig')[0], 401)

    def test_cross_origin_writes_are_refused(self):
        cookie = self.sign_in()
        evil = 'https://evil.example'
        self.assertEqual(self.call(self.col_port, 'PUT', {'data': {}}, cookie=cookie, origin=evil)[0], 403)
        self.assertEqual(self.call(self.col_port, 'DELETE', cookie=cookie, origin=evil)[0], 403)
        self.assertEqual(self.call(self.auth_port, 'POST', {'action': 'logout'}, origin=evil)[0], 403)

    def test_invalid_email_and_rate_limit(self):
        self.assertEqual(self.call(self.auth_port, 'POST', {'action': 'magic_request', 'email': 'nope'})[0], 400)
        codes = [self.call(self.auth_port, 'POST', {'action': 'magic_request', 'email': 'a@example.com'})[0] for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])
        self.assertEqual(len(self.emails), 3)

    def test_google_failure_is_401_and_logout_always_clears(self):
        status, _, cookie = self.call(self.auth_port, 'POST', {'action': 'google', 'credential': 'x' * 40})
        self.assertEqual((status, cookie), (401, None))
        status, _, cleared = self.call(self.auth_port, 'POST', {'action': 'logout'})
        self.assertEqual(status, 200)
        self.assertIn('Max-Age=0', cleared)


if __name__ == '__main__':
    unittest.main()
