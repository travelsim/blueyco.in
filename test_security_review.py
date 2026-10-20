"""Regression tests from the security review of the live Vercel surface.

Covers api/prices.py, api/buy-options.py, api/checkout.py and the inline
script in index.html. Tests named *_guard pin behaviour that was already
correct, so a later change cannot quietly reopen it.
"""
import http.client
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

ROOT = os.path.dirname(os.path.abspath(__file__))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, 'api', filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prices = _load('sec_review_prices', 'prices.py')
buy_options = _load('sec_review_buy_options', 'buy-options.py')
checkout = _load('sec_review_checkout', 'checkout.py')

HTML = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()


class _Served(unittest.TestCase):
    """Run one handler on a real local socket for the duration of a test."""
    handler = None

    def setUp(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), self.handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]

    def request(self, method, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        headers = {'Content-Type': 'application/json'} if body is not None else {}
        conn.request(method, '/', body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data


class PricesErrorTests(_Served):
    handler = prices.handler

    def test_internal_error_text_is_not_echoed_to_visitors(self):
        boom = RuntimeError('cannot read /var/task/secret-path/ebay_cache.json')
        with mock.patch.object(prices, '_build_payload', side_effect=boom):
            status, body = self.request('GET')
        self.assertEqual(status, 500)
        self.assertNotIn(b'secret-path', body)
        self.assertNotIn(b'/var/task', body)
        self.assertEqual(json.loads(body), {'error': 'Could not load price data. Try again later.'})


class BuyOptionsRequestTests(_Served):
    handler = buy_options.handler

    def _raw_post(self, header_block):
        """Send headers only (no body) and collect whatever the server returns."""
        with socket.create_connection(('127.0.0.1', self.port), timeout=3) as sock:
            sock.sendall(
                b'POST / HTTP/1.1\r\nHost: 127.0.0.1\r\n' + header_block +
                b'Connection: close\r\n\r\n')
            chunks = []
            while True:
                try:
                    data = sock.recv(4096)
                except socket.timeout:
                    break
                if not data:
                    break
                chunks.append(data)
        return b''.join(chunks)

    def test_negative_content_length_is_refused_instead_of_read_to_eof(self):
        raw = self._raw_post(b'Content-Type: application/json\r\nContent-Length: -1\r\n')
        self.assertRegex(raw, rb'^HTTP/1\.[01] 400', raw[:120])

    def test_non_object_json_body_gets_a_json_400(self):
        for body in (b'[]', b'null', b'"Bluey"'):
            with self.subTest(body=body):
                status, data = self.request('POST', body)
                self.assertEqual(status, 400)
                self.assertIn('error', json.loads(data))

    def test_oversize_body_is_refused_guard(self):
        status, _ = self.request('POST', b'{"coinId":"' + b'a' * 5000 + b'"}')
        self.assertEqual(status, 413)

    def test_client_keywords_never_reach_the_retailer_lookup_guard(self):
        """The live path must search the catalogue query, never a caller's string."""
        with mock.patch.object(buy_options, 'get_buy_options', return_value=([], True)) as lookup:
            status, _ = self.request(
                'POST', json.dumps({'coinId': 's1_bluey', 'keywords': 'http://127.0.0.1:9/x'}).encode())
        self.assertEqual(status, 200)
        lookup.assert_called_once()
        self.assertEqual(lookup.call_args.args[1], buy_options.legacy.COIN_BY_ID['s1_bluey']['search'])


class CheckoutValidationTests(unittest.TestCase):
    def test_nan_price_is_not_a_purchasable_item(self):
        items, total, error = checkout.validate({'items': [{'name': 'Frame', 'price': float('nan')}]})
        self.assertIsNone(items)
        self.assertIsNone(total)
        self.assertEqual(error, 'No purchasable items in cart.')

    def test_nan_from_json_body_is_rejected_end_to_end(self):
        payload = json.loads('{"items":[{"name":"Frame","price":NaN}]}')
        items, _, error = checkout.validate(payload)
        self.assertIsNone(items)
        self.assertEqual(error, 'No purchasable items in cart.')

    def test_infinite_and_negative_prices_are_rejected_guard(self):
        for price in (float('inf'), -5, 0):
            with self.subTest(price=price):
                items, _, _ = checkout.validate({'items': [{'name': 'Frame', 'price': price}]})
                self.assertIsNone(items)

    def test_finite_price_is_still_accepted(self):
        items, total, error = checkout.validate({'items': [{'name': 'Frame', 'price': 89.5}]})
        self.assertIsNone(error)
        self.assertEqual(items, [{'name': 'Frame', 'price': 89.5}])
        self.assertEqual(total, 89.5)


class FrontendEscapingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_escape_helper_neutralises_markup_quotes_and_ampersands(self):
        match = re.search(r'^function escapeHtml\(val\) \{\n.*?^\}', HTML, re.S | re.M)
        self.assertIsNotNone(match, 'index.html must define escapeHtml(val)')
        program = match.group(0) + "\nprocess.stdout.write(escapeHtml(require('fs').readFileSync(0, 'utf8')));"
        payload = '<img src=x onerror="alert(1)">\'&'
        result = subprocess.run(['node', '-e', program], input=payload.encode(), capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr[:300])
        self.assertEqual(result.stdout.decode(), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&#39;&amp;')

    def test_frame_and_cart_innerhtml_templates_escape_their_fields(self):
        # Scan only innerHTML template literals. The toast() call also reads
        # frame.name, but it writes through textContent, so it is not a sink.
        exempt = {'frame.price', 'item.price', 'frame.id'}  # numbers, and catalogue ids in onclick
        templates = re.findall(r'\.innerHTML = `([\s\S]*?)`;', HTML)
        self.assertGreaterEqual(len(templates), 4)
        for template in templates:
            for expr in re.findall(r'\$\{([^}]*)\}', template):
                expr = expr.strip()
                if not re.search(r'\b(frame|item)\.', expr) or expr in exempt:
                    continue
                # msg keeps the failure short; printing the whole page would bury it.
                self.assertTrue(expr.startswith('escapeHtml('),
                                f'unescaped field in innerHTML template: ${{{expr}}}')
        for expr in ('${escapeHtml(frame.name)}', '${escapeHtml(frame.image)}',
                     '${escapeHtml(frame.imageAlt)}', '${escapeHtml(frame.type)}',
                     '${escapeHtml(frame.series.toUpperCase())}', '${escapeHtml(item.name)}',
                     '${escapeHtml(item.series.toUpperCase())}'):
            self.assertTrue(expr in HTML, f'missing escaped interpolation: {expr}')

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_safe_url_rejects_script_and_data_schemes_guard(self):
        match = re.search(r'^function safeUrl\(val\) \{\n.*?^\}', HTML, re.S | re.M)
        self.assertIsNotNone(match)
        program = match.group(0) + (
            "\nconst cases = ['javascript:alert(1)', ' JAVASCRIPT:alert(1)', 'data:text/html,<b>x</b>',"
            " 'https://www.ebay.com.au/itm/1', 'http://example.test/a'];"
            "process.stdout.write(JSON.stringify(cases.map(safeUrl)));")
        result = subprocess.run(['node', '-e', program], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr[:300])
        self.assertEqual(json.loads(result.stdout), [
            None, None, None, 'https://www.ebay.com.au/itm/1', 'http://example.test/a'])


if __name__ == '__main__':
    unittest.main()
