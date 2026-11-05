"""Seller usernames must stay out of public responses and committed price data."""
import io
import json
import unittest
from pathlib import Path
from unittest import mock

import server as legacy  # noqa: E402

from api import prices  # noqa: E402

ROOT = Path(__file__).resolve().parent


class TestSellerPrivacy(unittest.TestCase):
    def assert_no_seller_names(self, value, path='$'):
        if isinstance(value, dict):
            self.assertNotIn('seller', value, f'seller key at {path}')
            for key, item in value.items():
                self.assert_no_seller_names(item, f'{path}.{key}')
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self.assert_no_seller_names(item, f'{path}[{index}]')
        elif isinstance(value, str):
            self.assertIsNone(prices._SELLER_BOX.search(value), f'seller box line at {path}')

    def test_manual_ebay_sales_file_has_no_seller_names(self):
        data = json.loads((ROOT / 'manual_ebay_sales.json').read_text(encoding='utf-8'))
        self.assert_no_seller_names(data)

    def test_seller_box_pattern_flags_names_but_not_redacted_lines(self):
        self.assertIsNotNone(prices._SELLER_BOX.search('example-seller 100% positive (2K)'))
        self.assertIsNone(prices._SELLER_BOX.search('[seller] 100% positive (2K)'))
        self.assertIsNone(prices._SELLER_BOX.search('Sell one like this 100% positive (2K)'))

    def test_strip_helpers_drop_seller_keys(self):
        data = {'seller': 'example-seller', 'coins': [{'seller': 'shop-example', 'price': 5.0}]}
        for module in (prices, legacy):
            with self.subTest(module=module.__name__):
                self.assertEqual(module._strip_seller_names(data), {'coins': [{'price': 5.0}]})

    def test_strip_helpers_redact_seller_box_lines(self):
        text = 'Sell one like this\nexample-seller 100% positive (2K)\nSponsored'
        for module in (prices, legacy):
            with self.subTest(module=module.__name__):
                self.assertEqual(
                    module._strip_seller_names(text),
                    'Sell one like this\n[seller] 100% positive (2K)\nSponsored',
                )
                self.assertEqual(
                    module._strip_seller_names('example-seller 99.5% positive (12)'),
                    '[seller] 99.5% positive (12)',
                )

    def test_strip_helpers_do_not_mutate_input_and_are_idempotent(self):
        payload = {'a': {'seller': 'shop-example', 'raw_listing_text': 'example-seller 100% positive (2K)'}}
        before = json.dumps(payload, sort_keys=True)
        for module in (prices, legacy):
            with self.subTest(module=module.__name__):
                once = module._strip_seller_names(payload)
                self.assertEqual(json.dumps(payload, sort_keys=True), before)
                self.assertEqual(module._strip_seller_names(once), once)
                self.assert_no_seller_names(once)

    def test_prices_response_body_has_no_seller_names(self):
        payload = {
            's1_bluey': {
                'ebay': {'products': [{
                    'seller': 'example-seller',
                    'raw_listing_text': 'shop-example 100% positive (2K)\nSponsored',
                }]},
                'coinxchange': {'seller': 'shop-example', 'price': 5.0},
            },
        }
        handler = prices.handler.__new__(prices.handler)
        handler.requestline = 'GET /api/prices HTTP/1.1'
        handler.request_version = 'HTTP/1.1'
        handler.command = 'GET'
        handler.client_address = ('127.0.0.1', 0)
        handler.wfile = io.BytesIO()
        with mock.patch.object(prices, '_build_payload', return_value=(payload, True)), \
                mock.patch.object(prices.handler, 'log_message'):
            handler._respond()
        head, _, body = handler.wfile.getvalue().partition(b'\r\n\r\n')
        self.assertIn(b' 200 ', head.split(b'\r\n')[0])
        data = json.loads(body)
        self.assert_no_seller_names(data)
        self.assertEqual(
            data['s1_bluey']['ebay']['products'][0]['raw_listing_text'],
            '[seller] 100% positive (2K)\nSponsored',
        )
        self.assertEqual(data['s1_bluey']['coinxchange'], {'price': 5.0})

    def test_server_prices_route_strips_seller_names(self):
        payload = {'s1_bluey': {'coinxchange': {'seller': 'shop-example', 'price': 5.0}}}
        handler = legacy.Handler.__new__(legacy.Handler)
        handler.path = '/api/prices'
        handler.command = 'GET'
        handler.request_version = 'HTTP/1.1'
        handler.requestline = 'GET /api/prices HTTP/1.1'
        handler.client_address = ('127.0.0.1', 0)
        handler.wfile = io.BytesIO()
        with mock.patch.object(prices, '_build_payload', return_value=(payload, True)), \
                mock.patch.object(legacy.Handler, 'log_message'):
            handler.do_GET()
        head, _, body = handler.wfile.getvalue().partition(b'\r\n\r\n')
        self.assertIn(b' 200 ', head.split(b'\r\n')[0])
        data = json.loads(body)
        self.assert_no_seller_names(data)
        self.assertEqual(data['s1_bluey']['coinxchange'], {'price': 5.0})

    def test_server_price_history_route_strips_seller_names(self):
        history = [{'date': '2026-10-17', 'coins': {'s1_bluey': {'coinxchange': {'seller': 'shop-example', 'price': 5.0}}}}]
        handler = legacy.Handler.__new__(legacy.Handler)
        handler.path = '/api/price-history?coinId=s1_bluey'
        handler._json = mock.Mock()
        with mock.patch.object(legacy, '_price_history', history):
            handler.do_GET()
        status, body = handler._json.call_args.args[:2]
        self.assertEqual(status, 200)
        self.assert_no_seller_names(body)
        self.assertEqual(body['count'], 1)
        self.assertEqual(body['snapshots'][0]['coinxchange'], {'price': 5.0})

    def test_cached_snapshot_has_no_seller_names_after_strip(self):
        snapshot = prices._cached_snapshot(
            prices.COINS, prices._load_base_cache(), prices._load_manual(), prices._load_manual_ebay_sales(),
        )
        self.assert_no_seller_names(prices._strip_seller_names(snapshot))

    def test_gtag_page_location_drops_hash_fragments(self):
        # #login= carries a magic-link token and #swap= a collection share.
        html = (ROOT / 'index.html').read_text(encoding='utf-8')
        self.assertIn(
            "gtag('config', 'G-0KYR0YPVN9', { page_location: location.origin + location.pathname + location.search });",
            html,
        )
