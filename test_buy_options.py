import importlib.util
import os
import time
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    'buy_options', os.path.join(_ROOT, 'api', 'buy-options.py')
)
buy_options = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(buy_options)

import server as legacy  # noqa: E402

from api import prices  # noqa: E402


class TestBuyOptions(unittest.TestCase):
    def setUp(self):
        buy_options._cache.clear()

    def test_every_retailer_yields_an_option(self):
        options, complete = buy_options.get_buy_options('s1_bluey', '2024 Bluey Dollarbuck Bluey')
        retailer_ids = {o['retailer_id'] for o in options}
        for r in legacy.RETAILERS:
            self.assertIn(r['id'], retailer_ids)
        self.assertTrue(all(o.get('url') for o in options))
        self.assertTrue(complete)

    def test_priced_options_sort_before_link_only(self):
        options, _ = buy_options.get_buy_options('s1_bluey', '2024 Bluey Dollarbuck Bluey')
        seen_link_only = False
        for o in options:
            if o.get('link_only') or o.get('price') is None:
                seen_link_only = True
            else:
                self.assertFalse(seen_link_only, 'priced option after a link-only option')

    def test_manual_override_takes_priority(self):
        manual = {'s1_bluey': {'ramint': {
            'price': 42.0, 'checkedAt': time.time(),
            'url': 'https://example.test/bluey',
        }}}
        original = buy_options._manual
        buy_options._manual = lambda: manual
        try:
            option = buy_options._fallback(legacy.RETAILERS[0], '2024 Bluey', 's1_bluey', manual)[0]
        finally:
            buy_options._manual = original
        self.assertEqual(option['price'], 42.0)
        self.assertEqual(option['url'], 'https://example.test/bluey')
        self.assertFalse(option['link_only'])
        self.assertEqual(option['price_type'], 'asking')

    def test_cash_converters_and_gumtree_remain_search_only(self):
        retailers = {r['id']: r for r in legacy.RETAILERS}
        for retailer_id in ('cashconverters', 'gumtree'):
            retailer = retailers[retailer_id]
            self.assertEqual(retailer['type'], 'link_only')
            with mock.patch.object(legacy, '_http_get', side_effect=AssertionError('network access')):
                self.assertEqual(buy_options._scrape(retailer, '2024 Bluey coin', 's1_bluey'), [])
            option = buy_options._fallback(retailer, '2024 Bluey coin', 's1_bluey', {})[0]
            self.assertTrue(option['link_only'])
            self.assertIsNone(option['price'])
            self.assertIn('2024', option['url'])
        self.assertNotIn('query=', retailers['cashconverters']['search_url'])

    def test_coinxchange_active_asks_are_identity_and_quantity_filtered(self):
        retailer = {r['id']: r for r in legacy.RETAILERS}['coinxchange_buy']
        self.assertEqual(retailer['type'], 'coinxchange')
        raw = [
            {'title': '2024 Bluey Dollarbuck till coin', 'price': 12.0, 'url': 'https://cx.test/1'},
            {'title': '2023 Bluey Dollarbuck till coin', 'price': 8.0, 'url': 'https://cx.test/2'},
            {'title': '2024 Bluey Dollarbuck bag of 20 coins', 'price': 30.0, 'url': 'https://cx.test/3'},
        ]
        with mock.patch.object(legacy, '_scrape_coinxchange', return_value=raw):
            options = buy_options._scrape(retailer, '2024 Bluey Dollarbuck till coin', 's1_bluey')
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]['price'], 12.0)
        self.assertEqual(options[0]['price_type'], 'asking')
        self.assertEqual(options[0]['title'], '2024 Bluey Dollarbuck till coin')

    def test_manual_price_without_recent_check_date_is_search_only(self):
        manual = {'s1_bluey': {'ramint': {
            'price': 42.0, 'url': 'https://example.test/bluey',
        }}}
        option = buy_options._fallback(
            legacy.RETAILERS[0], '2024 Bluey', 's1_bluey', manual)[0]
        self.assertIsNone(option['price'])
        self.assertTrue(option['link_only'])

    def test_result_is_cached(self):
        first, _ = buy_options.get_buy_options('s1_bingo', '2024 Bluey Dollarbuck Bingo')
        cached = buy_options._cache['s1_bingo']['options']
        second, _ = buy_options.get_buy_options('s1_bingo', '2024 Bluey Dollarbuck Bingo')
        self.assertEqual(first, second)
        self.assertEqual(cached, second)

    def test_unknown_coin_is_rejected(self):
        self.assertNotIn('does_not_exist', legacy.COIN_BY_ID)


class TestCatalogueParity(unittest.TestCase):
    def test_prices_catalogue_matches_legacy_server(self):
        self.assertEqual(
            {c['id'] for c in prices.COINS},
            set(legacy.COIN_BY_ID),
        )

    def test_catalogue_has_no_duplicate_ids(self):
        ids = [c['id'] for c in prices.COINS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_coin_has_search_keywords(self):
        for coin in prices.COINS:
            self.assertTrue(coin.get('search'), coin['id'])
            self.assertTrue(coin.get('ebay_kw'), coin['id'])


class TestCoinXchangeParser(unittest.TestCase):
    def test_sold_record_parses_sale_price_date_and_postage_separately(self):
        lines = [
            '2024 Bluey Dollarbuck till coin', 'AU $12.00', 'Buy It Now',
            '+AU $5.00 postage', 'Sold 1 Oct 2026', 'seller-id', '(3)', '100%',
        ]
        hrefs = ['/item/1'] + [None] * (len(lines) - 1)
        record = legacy._cx_parse_sold(lines, hrefs)[0]
        self.assertEqual(record['price'], 12.0)
        self.assertEqual(record['postage'], 5.0)
        self.assertEqual(record['currency'], 'AUD')
        self.assertEqual(record['sold_date'], '1 Oct 2026')
        self.assertEqual(record['seller'], 'seller-id')


if __name__ == '__main__':
    unittest.main()
