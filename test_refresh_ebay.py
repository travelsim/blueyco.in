import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from scripts import refresh_ebay


class RefreshEbayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self.temp.name, 'ebay_cache.json')
        self.old_root = refresh_ebay.ROOT
        refresh_ebay.ROOT = self.temp.name
        self.old_cache = {
            'coin-a': {'ebay': {
                'products': [{'title': '2024 Bluey coin', 'sale_price': 8.0,
                              'currency': 'AU', 'date_sold': '1 Jan 2025',
                              'item_id': 'old-1'}],
                'historical_products': [],
            }}
        }
        with open(self.cache_path, 'w', encoding='utf-8') as stream:
            json.dump(self.old_cache, stream)
        self.old_coins = refresh_ebay.prices.COINS
        refresh_ebay.prices.COINS = [{'id': 'coin-a', 'ebay_kw': '2024 Bluey coin'}]

    def tearDown(self):
        refresh_ebay.ROOT = self.old_root
        refresh_ebay.prices.COINS = self.old_coins
        self.temp.cleanup()

    def read_cache(self):
        with open(self.cache_path, encoding='utf-8') as stream:
            return json.load(stream)

    def test_refresh_preserves_old_sales_as_history(self):
        with patch.object(refresh_ebay.prices, 'RAPIDAPI_KEY', 'configured'), \
             patch.object(refresh_ebay.prices, '_fetch_ebay', return_value={
                'products': [{'title': '2024 Bluey coin', 'sale_price': 9.0,
                               'currency': 'AU', 'date_sold': datetime.now(timezone.utc).strftime('%d %b %Y'),
                               'item_id': 'new-1'}],
                 'total_results': 1,
             }):
            refresh_ebay.refresh()

        ebay = self.read_cache()['coin-a']['ebay']
        self.assertEqual([p['item_id'] for p in ebay['products']], ['new-1'])
        self.assertEqual([p['item_id'] for p in ebay['historical_products']], ['old-1'])

    def test_failed_batch_does_not_write_any_snapshot_changes(self):
        before = self.read_cache()
        with patch.object(refresh_ebay.prices, 'RAPIDAPI_KEY', 'configured'), \
             patch.object(refresh_ebay.prices, '_fetch_ebay', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'without saving'):
                refresh_ebay.refresh()
        self.assertEqual(self.read_cache(), before)

    def test_missing_key_makes_no_requests_or_writes(self):
        before = self.read_cache()
        with patch.object(refresh_ebay.prices, 'RAPIDAPI_KEY', ''), \
             patch.object(refresh_ebay.prices, '_fetch_ebay') as fetch:
            with self.assertRaisesRegex(RuntimeError, 'not configured'):
                refresh_ebay.refresh()
        fetch.assert_not_called()
        self.assertEqual(self.read_cache(), before)


class SleepytimeRefreshGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self.temp.name, 'ebay_cache.json')
        self.old_root = refresh_ebay.ROOT
        refresh_ebay.ROOT = self.temp.name
        with open(self.cache_path, 'w', encoding='utf-8') as stream:
            json.dump({}, stream)
        self.old_coins = refresh_ebay.prices.COINS
        self.real_coin = next(c for c in refresh_ebay.prices.COINS
                              if c['id'] == '76604949')
        refresh_ebay.prices.COINS = [self.real_coin]

    def tearDown(self):
        refresh_ebay.ROOT = self.old_root
        refresh_ebay.prices.COINS = self.old_coins
        self.temp.cleanup()

    def test_bundle_observation_is_marked_ineligible_upstream(self):
        product = {'title': '2026 $2 Bluey Sleepytime PNC IN HAND + 2 till coins',
                   'sale_price': 106.7, 'currency': 'AU',
                   'date_sold': datetime.now(timezone.utc).strftime('%d %b %Y'),
                   'item_id': '840166097677'}
        with patch.object(refresh_ebay.prices, 'RAPIDAPI_KEY', 'configured'), \
                patch.object(refresh_ebay.prices, '_fetch_ebay',
                             return_value={'products': [product],
                                           'total_results': 1}):
            refresh_ebay.refresh()
        with open(self.cache_path, encoding='utf-8') as stream:
            sale = json.load(stream)['76604949']['ebay']['products'][0]
        self.assertIs(sale['value_eligible'], False)
        self.assertEqual(sale['review_flag'], 'bundle')

    def test_clean_observation_keeps_its_price(self):
        product = {'title': '2026 Bluey Sleepytime Limited-Edition PNC coloured $2',
                   'sale_price': 126.84, 'currency': 'AU',
                   'date_sold': datetime.now(timezone.utc).strftime('%d %b %Y'),
                   'item_id': '860179205712'}
        with patch.object(refresh_ebay.prices, 'RAPIDAPI_KEY', 'configured'), \
                patch.object(refresh_ebay.prices, '_fetch_ebay',
                             return_value={'products': [product],
                                           'total_results': 1}):
            refresh_ebay.refresh()
        with open(self.cache_path, encoding='utf-8') as stream:
            sale = json.load(stream)['76604949']['ebay']['products'][0]
        self.assertNotIn('value_eligible', sale)
        self.assertEqual(sale['sale_price'], 126.84)


if __name__ == '__main__':
    unittest.main()
