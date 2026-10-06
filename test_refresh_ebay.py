import json
import os
import tempfile
import unittest
from datetime import datetime
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
                               'currency': 'AU', 'date_sold': datetime.now().strftime('%d %b %Y'),
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


if __name__ == '__main__':
    unittest.main()
