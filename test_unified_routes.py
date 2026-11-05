"""Every route the front end calls, served by one server.Handler over real HTTP.

Each route is checked against the status the Vercel function returns for the
same request. The handlers themselves are the ones in api/, so these tests cover
the wiring in server.py and the app shell fallback that vercel.json provided.
"""
import http.client
import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'api'))
import _auth as A  # noqa: E402
import server  # noqa: E402
from server import _api_module  # noqa: E402

ENV = {
    'SESSION_SECRET': 'test-secret-value-0123456789',
    'AUTH_STORE': 'memory',
    'GOOGLE_CLIENT_ID': 'client-123.apps.googleusercontent.com',
    'SMTP_HOST': 'smtp.example.test',
    'SMTP_USER': 'login@example.test',
    'SMTP_PASSWORD': 'not-a-real-password',
    'SMTP_FROM': 'login@example.test',
}
UNCONFIGURED = {'SESSION_SECRET': '', 'AUTH_STORE': '', 'KV_REST_API_URL': '', 'KV_REST_API_TOKEN': ''}


class RoutesOverHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        A._memory_store.data.clear()
        self.emails = []
        sender = mock.patch.object(A, 'send_magic_email', lambda email, token: self.emails.append((email, token)))
        sender.start()
        self.addCleanup(sender.stop)

    def request(self, method, path, body=None, cookie=None, origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        headers = {}
        raw = None
        if body is not None:
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
            headers['Content-Length'] = str(len(raw))
        if cookie:
            headers['Cookie'] = cookie
        if origin:
            headers['Origin'] = origin
        conn.request(method, path, body=raw, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, data

    def json_call(self, method, path, body=None, cookie=None, origin=None):
        resp, data = self.request(method, path, body=body, cookie=cookie, origin=origin)
        return resp.status, json.loads(data or b'{}'), resp

    def sign_in(self, email='jane@example.com'):
        self.json_call('POST', '/api/auth', {'action': 'magic_request', 'email': email})
        token = self.emails[-1][1]
        status, _, resp = self.json_call('POST', '/api/auth', {'action': 'magic_verify', 'token': token})
        self.assertEqual(status, 200)
        return resp.getheader('Set-Cookie').split(';')[0]

    # ── /api/auth ───────────────────────────────────────────────────────────
    def test_auth_config_reports_methods_and_no_user(self):
        status, data, _ = self.json_call('GET', '/api/auth')
        self.assertEqual(status, 200)
        self.assertEqual(data, {
            'google': True,
            'googleClientId': ENV['GOOGLE_CLIENT_ID'],
            'magic': True,
            'user': None,
        })

    def test_auth_is_503_without_secrets(self):
        with mock.patch.dict(os.environ, UNCONFIGURED):
            status, data, _ = self.json_call('GET', '/api/auth')
            self.assertEqual((status, data['google'], data['magic'], data['googleClientId']), (200, False, False, ''))
            status, _, _ = self.json_call('POST', '/api/auth', {'action': 'magic_request', 'email': 'a@example.com'})
            self.assertEqual(status, 503)
            status, _, _ = self.json_call('POST', '/api/auth', {'action': 'google', 'credential': 'x' * 40})
            self.assertEqual(status, 503)

    def test_magic_link_signs_in_and_cannot_be_replayed(self):
        status, data, _ = self.json_call('POST', '/api/auth', {'action': 'magic_request', 'email': 'Jane@Example.com'})
        self.assertEqual(status, 200)
        self.assertTrue(data['sent'])
        self.assertEqual(self.emails[-1][0], 'jane@example.com')
        token = self.emails[-1][1]

        status, data, resp = self.json_call('POST', '/api/auth', {'action': 'magic_verify', 'token': token})
        self.assertEqual(status, 200)
        self.assertEqual(data['user']['email'], 'j***@example.com')
        cookie = resp.getheader('Set-Cookie')
        self.assertIn(A.SESSION_COOKIE + '=', cookie)
        self.assertIn('HttpOnly', cookie)

        status, data, _ = self.json_call('GET', '/api/auth', cookie=cookie.split(';')[0])
        self.assertEqual(data['user'], {'email': 'j***@example.com'})

        status, _, _ = self.json_call('POST', '/api/auth', {'action': 'magic_verify', 'token': token})
        self.assertEqual(status, 401)

    def test_logout_clears_the_session_cookie(self):
        status, data, resp = self.json_call('POST', '/api/auth', {'action': 'logout'})
        self.assertEqual((status, data), (200, {'ok': True}))
        self.assertIn('Max-Age=0', resp.getheader('Set-Cookie'))

    def test_auth_rejects_bad_input_and_cross_site_writes(self):
        status, _, _ = self.json_call('POST', '/api/auth', {'action': 'magic_request', 'email': 'not-an-email'})
        self.assertEqual(status, 400)
        status, _, _ = self.json_call('POST', '/api/auth', {'action': 'something-else'})
        self.assertEqual(status, 400)
        status, _, _ = self.json_call('POST', '/api/auth', {'action': 'magic_request', 'email': 'a@example.com'},
                                      origin='https://evil.example')
        self.assertEqual(status, 403)
        self.assertEqual(self.emails, [])

    def test_auth_put_is_501_like_vercel(self):
        resp, _ = self.request('PUT', '/api/auth', body={})
        self.assertEqual(resp.status, 501)

    # ── /api/collection ─────────────────────────────────────────────────────
    def test_collection_needs_a_session(self):
        status, _, _ = self.json_call('GET', '/api/collection')
        self.assertEqual(status, 401)
        status, _, _ = self.json_call('PUT', '/api/collection', {'data': {}})
        self.assertEqual(status, 401)

    def test_collection_round_trip_and_delete(self):
        cookie = self.sign_in()
        status, data, _ = self.json_call('GET', '/api/collection', cookie=cookie)
        self.assertEqual((status, data['data']['collection']), (200, {}))

        status, data, _ = self.json_call('PUT', '/api/collection',
                                         {'data': {'collection': {'s1_bluey': True}}}, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn('updatedAt', data)
        status, data, _ = self.json_call('GET', '/api/collection', cookie=cookie)
        self.assertEqual(data['data']['collection'], {'s1_bluey': True})

        status, data, resp = self.json_call('DELETE', '/api/collection', cookie=cookie)
        self.assertEqual((status, data), (200, {'deleted': True}))
        self.assertIn('Max-Age=0', resp.getheader('Set-Cookie'))
        status, data, _ = self.json_call('GET', '/api/collection', cookie=cookie)
        self.assertEqual(data['data']['collection'], {})

    def test_collection_refuses_cross_site_writes(self):
        cookie = self.sign_in()
        status, _, _ = self.json_call('PUT', '/api/collection', {'data': {}}, cookie=cookie,
                                      origin='https://evil.example')
        self.assertEqual(status, 403)

    def test_collection_post_is_501_like_vercel(self):
        resp, _ = self.request('POST', '/api/collection', body={})
        self.assertEqual(resp.status, 501)

    # ── /api/checkout ───────────────────────────────────────────────────────
    def test_checkout_rejects_an_empty_cart(self):
        status, data, _ = self.json_call('POST', '/api/checkout', {'items': []})
        self.assertEqual((status, data), (400, {'error': 'Cart is empty.'}))

    def test_checkout_is_501_until_a_payment_link_is_set(self):
        module = _api_module('checkout')
        with mock.patch.object(module, 'PAYMENT_LINK', ''):
            status, data, _ = self.json_call('POST', '/api/checkout',
                                             {'items': [{'name': 'Frame', 'price': 49.5}]})
        self.assertEqual(status, 501)
        self.assertEqual(data['total'], 49.5)
        self.assertIn('not switched on', data['error'])

    def test_checkout_returns_the_payment_link_when_configured(self):
        module = _api_module('checkout')
        with mock.patch.object(module, 'PAYMENT_LINK', 'https://buy.stripe.test/link'):
            status, data, _ = self.json_call('POST', '/api/checkout',
                                             {'items': [{'name': 'Frame', 'price': 49.5}]})
        self.assertEqual(status, 200)
        self.assertEqual(data['checkoutUrl'], 'https://buy.stripe.test/link')
        self.assertEqual(data['total'], 49.5)

    def test_checkout_get_is_405(self):
        status, _, _ = self.json_call('GET', '/api/checkout')
        self.assertEqual(status, 405)

    # ── /api/contact ────────────────────────────────────────────────────────
    def test_contact_rejects_an_incomplete_request(self):
        status, data, _ = self.json_call('POST', '/api/contact', {'name': '', 'email': 'a@example.com', 'coin': 'x'})
        self.assertEqual((status, data), (400, {'error': 'Name is required.'}))

    def test_contact_without_a_webhook_is_202_not_delivered(self):
        module = _api_module('contact')
        with mock.patch.object(module, 'WEBHOOK_URL', ''):
            status, data, _ = self.json_call('POST', '/api/contact',
                                             {'name': 'Jane', 'email': 'jane@example.com', 'coin': '1966 Penny'})
        self.assertEqual(status, 202)
        self.assertFalse(data['delivered'])

    def test_contact_delivered_is_200(self):
        module = _api_module('contact')
        with mock.patch.object(module, 'deliver', return_value=(True, None)) as deliver:
            status, data, _ = self.json_call('POST', '/api/contact',
                                             {'name': 'Jane', 'email': 'Jane@Example.com', 'coin': '1966 Penny'})
        self.assertEqual(status, 200)
        self.assertTrue(data['delivered'])
        self.assertEqual(deliver.call_args.args[0]['email'], 'jane@example.com')

    def test_contact_get_is_405(self):
        status, _, _ = self.json_call('GET', '/api/contact')
        self.assertEqual(status, 405)

    # ── app shell, static files and Vercel's path rules ─────────────────────
    def test_unknown_page_gets_the_app_shell(self):
        resp, data = self.request('GET', '/some/deep/page')
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.getheader('Content-Type', '').startswith('text/html'))
        self.assertEqual(data, (ROOT / 'index.html').read_bytes())

    def test_app_path_redirects_home_permanently(self):
        resp, _ = self.request('GET', '/app')
        self.assertEqual(resp.status, 308)
        self.assertEqual(resp.getheader('Location'), '/')

    def test_vercel_internal_paths_are_404(self):
        resp, _ = self.request('GET', '/_vercel/insights/script.js')
        self.assertEqual(resp.status, 404)

    def test_unknown_api_path_is_404(self):
        resp, _ = self.request('GET', '/api/nope')
        self.assertEqual(resp.status, 404)

    def test_ballot_and_distributor_pages_are_served(self):
        for path, fname in (('/ballot/', 'ballot/index.html'), ('/distributors/', 'distributors/index.html')):
            with self.subTest(path=path):
                resp, data = self.request('GET', path)
                self.assertEqual(resp.status, 200)
                self.assertEqual(data, (ROOT / fname).read_bytes())

    def test_coin_image_is_served_with_its_type(self):
        name = sorted(p.name for p in (ROOT / 'coin-images').glob('*.jpg'))[0]
        resp, data = self.request('GET', '/coin-images/' + name)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader('Content-Type'), 'image/jpeg')
        self.assertEqual(data, (ROOT / 'coin-images' / name).read_bytes())

    def test_missing_asset_is_404_not_the_app_shell(self):
        resp, _ = self.request('GET', '/coin-images/does-not-exist.jpg')
        self.assertEqual(resp.status, 404)

    def test_hidden_and_code_files_are_never_served(self):
        for path in ('/coin-images/.env.jpg', '/coin-images/../server.py', '/frames/../test_auth.py'):
            with self.subTest(path=path):
                resp, data = self.request('GET', path)
                self.assertEqual(resp.status, 404)
                self.assertNotIn(b'import ', data)

    def test_root_static_files_are_served(self):
        resp, data = self.request('GET', '/robots.txt')
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.getheader('Content-Type', '').startswith('text/plain'))
        self.assertEqual(data, (ROOT / 'robots.txt').read_bytes())

    def test_put_and_delete_outside_api_are_404(self):
        self.assertEqual(self.request('PUT', '/nope', body={})[0].status, 404)
        self.assertEqual(self.request('DELETE', '/nope')[0].status, 404)


if __name__ == '__main__':
    unittest.main()
