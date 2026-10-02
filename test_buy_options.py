import importlib.util
import os
import unittest

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
        manual = {'s1_bluey': {'ramint': {'price': 42.0, 'url': 'https://example.test/bluey'}}}
        original = buy_options._manual
        buy_options._manual = lambda: manual
        try:
            option = buy_options._fallback(legacy.RETAILERS[0], '2024 Bluey', 's1_bluey', manual)[0]
        finally:
            buy_options._manual = original
        self.assertEqual(option['price'], 42.0)
        self.assertEqual(option['url'], 'https://example.test/bluey')
        self.assertFalse(option['link_only'])

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


if __name__ == '__main__':
    unittest.main()