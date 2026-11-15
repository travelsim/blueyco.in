import atexit
import http.client
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import HTTPServer
from unittest import mock

API = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'api')
sys.path.insert(0, API)
import _auth as A  # noqa: E402

CLIENT = 'com.example.bluey.web'
ENV = {
    'SESSION_SECRET': 'test-secret-value-0123456789',
    'AUTH_STORE': 'memory',
    'APPLE_CLIENT_ID': CLIENT,
}
HAS_OPENSSL = shutil.which('openssl') is not None
_STATE = {}


def _load(name):
    spec = importlib.util.spec_from_file_location('api_' + name, os.path.join(API, name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUTH_API = _load('auth')


def _keys():
    """Generate a throwaway RSA key with the openssl CLI, once per run."""
    if not _STATE:
        workdir = tempfile.mkdtemp()
        atexit.register(shutil.rmtree, workdir, True)
        key = os.path.join(workdir, 'k.pem')
        subprocess.run(['openssl', 'genrsa', '-out', key, '2048'], check=True, capture_output=True)
        modulus = subprocess.run(['openssl', 'rsa', '-in', key, '-noout', '-modulus'],
                                 check=True, capture_output=True, text=True).stdout.strip()
        n = int(modulus.split('=', 1)[1], 16)
        _STATE.update(key=key, jwks={'keys': [{
            'kty': 'RSA', 'kid': 'kid-1', 'alg': 'RS256', 'use': 'sig',
            'n': A._b64(n.to_bytes((n.bit_length() + 7) // 8, 'big')),
            'e': A._b64((65537).to_bytes(3, 'big')),
        }]})
    return _STATE


def _sign(message):
    return subprocess.run(['openssl', 'dgst', '-sha256', '-sign', _keys()['key']],
                          input=message, capture_output=True, check=True).stdout


def make_token(claims=None, header=None):
    head = {'alg': 'RS256', 'kid': 'kid-1'} if header is None else header
    body = {'iss': A.APPLE_ISSUER, 'aud': CLIENT, 'exp': int(time.time()) + 600,
            'iat': int(time.time()), 'sub': '001234.abcd.5678',
            'email': 'jane@privaterelay.appleid.com', 'email_verified': 'true'}
    body.update(claims or {})
    h = A._b64(json.dumps(head).encode())
    p = A._b64(json.dumps(body).encode())
    return f'{h}.{p}.{A._b64(_sign(f"{h}.{p}".encode()))}'


def verify(token, fetch=None):
    with mock.patch.dict(os.environ, ENV), \
            mock.patch.object(A, '_apple_keys_cache', {'at': 0.0, 'keys': []}):
        return A.verify_apple_identity_token(token, fetch=fetch or (lambda url: _keys()['jwks']))


@unittest.skipUnless(HAS_OPENSSL, 'needs the openssl CLI to sign test tokens')
class AppleTokenTests(unittest.TestCase):
    def test_valid_token_returns_apple_claims(self):
        claims = verify(make_token())
        self.assertEqual(claims['sub'], '001234.abcd.5678')
        self.assertEqual(claims['email'], 'jane@privaterelay.appleid.com')

    def test_wrong_audience_issuer_or_expiry_is_rejected(self):
        self.assertIsNone(verify(make_token({'aud': 'com.someone.else'})))
        self.assertIsNone(verify(make_token({'iss': 'https://evil.example'})))
        self.assertIsNone(verify(make_token({'exp': int(time.time()) - 1})))
        self.assertIsNone(verify(make_token({'sub': ''})))

    def test_tampered_payload_is_rejected(self):
        original = make_token()
        head, _, sig = original.split('.')
        forged = A._b64(json.dumps({'iss': A.APPLE_ISSUER, 'aud': CLIENT, 'exp': int(time.time()) + 600,
                                    'sub': 'attacker'}).encode())
        self.assertIsNone(verify(f'{head}.{forged}.{sig}'))

    def test_wrong_algorithm_key_or_shape_is_rejected(self):
        self.assertIsNone(verify(make_token(header={'alg': 'HS256', 'kid': 'kid-1'})))
        self.assertIsNone(verify(make_token(header={'alg': 'none', 'kid': 'kid-1'})))
        self.assertIsNone(verify(make_token(header={'alg': 'RS256', 'kid': 'unknown'})))
        self.assertIsNone(verify('a.b'))
        self.assertIsNone(verify('x' * 9000))
        self.assertIsNone(verify(None))

    def test_unreachable_apple_keys_fail_closed(self):
        def down(url):
            raise OSError('apple unreachable')
        self.assertIsNone(verify(make_token(), fetch=down))

    def test_sign_in_is_off_without_client_id_or_secrets(self):
        with mock.patch.dict(os.environ, {'SESSION_SECRET': 'x' * 20, 'AUTH_STORE': 'memory'}, clear=True):
            self.assertFalse(A.apple_enabled())
        with mock.patch.dict(os.environ, {'APPLE_CLIENT_ID': CLIENT}, clear=True):
            self.assertFalse(A.apple_enabled())

    def test_apple_accounts_key_on_subject_not_email(self):
        self.assertEqual(A.apple_user_id('001234.abcd'), A.apple_user_id('001234.abcd'))
        self.assertNotEqual(A.apple_user_id('jane@example.com'), A.user_id('jane@example.com'))
        self.assertEqual(len(A.apple_user_id('001234.abcd')), 40)


@unittest.skipUnless(HAS_OPENSSL, 'needs the openssl CLI to sign test tokens')
class AppleEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(('127.0.0.1', 0), AUTH_API.handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        patchers = [
            mock.patch.dict(os.environ, ENV),
            mock.patch.object(A, '_memory_store', A.MemoryStore()),
            mock.patch.object(A, '_apple_keys_cache', {'at': 0.0, 'keys': []}),
            mock.patch.object(A, '_fetch_json', lambda url: _keys()['jwks']),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)

    def call(self, method, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers = {'Content-Type': 'application/json'}
        conn.request(method, '/', body=json.dumps(body) if body is not None else None, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read() or b'{}')
        set_cookie = resp.getheader('Set-Cookie')
        conn.close()
        return resp.status, data, set_cookie

    def test_config_advertises_apple_with_its_client_and_redirect(self):
        _, data, _ = self.call('GET')
        self.assertTrue(data['apple'])
        self.assertEqual(data['appleClientId'], CLIENT)
        self.assertEqual(data['appleRedirectUri'], 'https://blueyco.in/')

    def test_valid_token_signs_in_under_the_subject_account(self):
        token = make_token()
        status, data, set_cookie = self.call('POST', {'action': 'apple', 'credential': token})
        self.assertEqual(status, 200)
        self.assertEqual(data['user']['email'], 'j***@privaterelay.appleid.com')
        session = A.read_session(set_cookie.split(';')[0])
        self.assertEqual(session['uid'], A.apple_user_id('001234.abcd.5678'))
        self.assertIn('HttpOnly', set_cookie)

    def test_token_without_email_gets_a_generic_label(self):
        status, data, _ = self.call('POST', {'action': 'apple',
                                             'credential': make_token({'email': None})})
        self.assertEqual((status, data['user']['email']), (200, 'Apple account'))

    def test_wrong_audience_is_refused_without_a_cookie(self):
        status, _, set_cookie = self.call('POST', {'action': 'apple',
                                                   'credential': make_token({'aud': 'other.app'})})
        self.assertEqual(status, 401)
        self.assertIsNone(set_cookie)

    def test_refused_while_unconfigured(self):
        env = {k: v for k, v in ENV.items() if k != 'APPLE_CLIENT_ID'}
        with mock.patch.dict(os.environ, env, clear=True):
            status, _, _ = self.call('POST', {'action': 'apple', 'credential': make_token()})
        self.assertEqual(status, 503)


if __name__ == '__main__':
    unittest.main()
