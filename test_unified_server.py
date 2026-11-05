"""One self-hosted process serves the static site and the two Vercel API routes.

Drives server.Handler over real HTTP and checks that /api/prices and
/api/buy-options answer the way the Vercel handlers in api/ do.
"""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

import server
from server import _api_module


class UnifiedServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        headers = {}
        raw = None
        if body is not None:
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            headers = {'Content-Type': 'application/json', 'Content-Length': str(len(raw))}
        conn.request(method, path, body=raw, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, data

    def test_get_prices_serves_vercel_payload(self):
        resp, data = self.request('GET', '/api/prices')
        self.assertEqual(resp.status, 200)
        self.assertIn('s-maxage=', resp.getheader('Cache-Control'))
        self.assertIn(resp.getheader('X-Prices-Complete'), ('true', 'false'))
        body = json.loads(data)
        self.assertIsInstance(body, dict)
        self.assertIn('s1_bluey', body)

    def test_get_prices_ignores_query_string(self):
        resp, _ = self.request('GET', '/api/prices?v=123')
        self.assertEqual(resp.status, 200)

    def test_post_prices_matches_vercel_post(self):
        resp, data = self.request('POST', '/api/prices', body={})
        self.assertEqual(resp.status, 200)
        self.assertIn('s1_bluey', json.loads(data))

    def test_post_buy_options_unknown_coin_is_400(self):
        resp, data = self.request('POST', '/api/buy-options', body={'coinId': 'nope'})
        self.assertEqual(resp.status, 400)
        self.assertEqual(json.loads(data), {'error': 'Unknown coinId.'})

    def test_post_buy_options_returns_options_and_complete_header(self):
        module = _api_module('buy-options')
        fake = [{'retailer_id': 'ebay', 'name': 'eBay', 'price': None, 'link_only': True,
                 'url': 'https://example.test/x'}]
        with mock.patch.object(module, 'get_buy_options', return_value=(fake, True)):
            resp, data = self.request('POST', '/api/buy-options', body={'coinId': 's1_bluey'})
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader('X-Buy-Options-Complete'), 'true')
        self.assertEqual(json.loads(data), {'options': fake})

    def test_get_buy_options_is_405_like_vercel(self):
        resp, data = self.request('GET', '/api/buy-options')
        self.assertEqual(resp.status, 405)
        self.assertIn('Use POST', json.loads(data)['error'])

    def test_buy_options_rate_limit_applies_in_process(self):
        with mock.patch.object(server, '_is_rate_limited', return_value=True):
            resp, data = self.request('POST', '/api/buy-options', body={'coinId': 's1_bluey'})
        self.assertEqual(resp.status, 429)
        self.assertEqual(json.loads(data), {'error': 'Too many requests.'})

    def test_static_index_served_by_same_process(self):
        resp, data = self.request('GET', '/')
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.getheader('Content-Type', '').startswith('text/html'))
        self.assertGreater(len(data), 0)

    def test_unknown_post_path_is_404(self):
        resp, _ = self.request('POST', '/api/nope', body={})
        self.assertEqual(resp.status, 404)


if __name__ == '__main__':
    unittest.main()
