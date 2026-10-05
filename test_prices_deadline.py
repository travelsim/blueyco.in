import time
import unittest
from datetime import datetime, timezone
from unittest import mock

from api import prices


class TestPricesDeadline(unittest.TestCase):
    def setUp(self):
        prices._cache.clear()
        prices._last_fetch.clear()

    def test_slow_coins_return_partial_snapshot_before_deadline(self):
        coins = [{'id': f'c{i}', 'search': 'x', 'ebay_kw': 'x'} for i in range(40)]

        def fetch(coin):
            if coin['id'] in ('c3', 'c7'):
                time.sleep(2)
            return {'ebay': None, 'coinxchange': {'average_price': 10.0}}

        start = time.time()
        snapshot, complete = prices._build_payload(coins, fetch, deadline=0.5)
        self.assertLess(time.time() - start, 1.5)
        self.assertFalse(complete)
        self.assertEqual(len(snapshot), 40)
        self.assertIsNone(snapshot['c3']['coinxchange'])
        self.assertIsNone(snapshot['c0']['coinxchange'])
        self.assertIn('manual', snapshot['c3'])

    def test_complete_snapshot_is_cached(self):
        coins = [{'id': 'a', 'search': 'x', 'ebay_kw': 'x'}]
        calls = []

        def fetch(coin):
            calls.append(coin['id'])
            return {'ebay': None, 'coinxchange': None}

        _, complete = prices._build_payload(coins, fetch, deadline=1)
        prices._build_payload(coins, fetch, deadline=1)
        self.assertTrue(complete)
        self.assertEqual(calls, ['a'])

    def test_baseline_cache_is_used_when_ebay_not_fetched(self):
        def fetch_no_ebay(coin):
            return {'ebay': None, 'coinxchange': None}

        snapshot, complete = prices._build_payload(
            [c for c in prices.COINS if c['id'] == 's1_bluey'],
            fetch_coin=fetch_no_ebay,
            deadline=1,
        )
        self.assertIsNotNone(snapshot['s1_bluey']['ebay'])
        self.assertIsNone(snapshot['s1_bluey']['coinxchange'])


if __name__ == '__main__':
    unittest.main()


class TestCoinXchangeDelegation(unittest.TestCase):
    def test_prices_does_not_access_coinxchange_automatically(self):
        with mock.patch.object(prices, '_http_get', side_effect=AssertionError('network access')):
            self.assertEqual(prices._scrape_coinxchange('Bluey'), [])


class TestPricesRateLimit(unittest.TestCase):
    def setUp(self):
        prices._cache.clear()
        prices._last_fetch.clear()
        prices._last_rapidapi_request = 0.0

    def test_default_path_is_cache_first_when_live_refresh_is_disabled(self):
        coin = {'id': 'a', 'search': 'x', 'ebay_kw': 'x'}
        baseline = {
            'a': {
                'ebay': {'average_price': 12.95, 'products': [
                    {'title': 'x', 'sale_price': 12.95, 'currency': 'AU',
                     'date_sold': '1 Oct 2026'}]},
                'coinxchange': {'average_price': 10.0},
            }
        }

        with mock.patch.object(prices, '_load_base_cache', return_value=baseline), \
             mock.patch.object(prices, '_load_manual', return_value={}), \
             mock.patch.object(prices, 'RAPIDAPI_LIVE_REFRESH', False), \
             mock.patch.object(prices, '_fetch_coin', side_effect=AssertionError('unexpected fan-out')):
            snapshot, complete = prices._build_payload([coin], deadline=1)

        self.assertTrue(complete)
        self.assertEqual(snapshot['a']['ebay']['average_price'], 12.95)
        self.assertIsNone(snapshot['a']['coinxchange'])

    def test_429_does_not_replace_cached_ebay(self):
        coin = {'id': 'a', 'search': 'x', 'ebay_kw': 'x'}
        baseline = {
            'a': {
                'ebay': {'average_price': 12.95, 'products': [
                    {'title': 'x', 'sale_price': 12.95, 'currency': 'AU',
                     'date_sold': '1 Oct 2026'}]},
                'coinxchange': None,
            }
        }

        def fetch(_coin):
            return {
                'ebay': {
                    'error': 'HTTP Error 429: Too Many Requests',
                    'average_price': None,
                    'products': [],
                },
                'coinxchange': None,
            }

        with mock.patch.object(prices, '_load_base_cache', return_value=baseline), \
             mock.patch.object(prices, '_load_manual', return_value={}):
            snapshot, _ = prices._build_payload([coin], fetch_coin=fetch, deadline=1)

        self.assertEqual(snapshot['a']['ebay']['average_price'], 12.95)

    def test_rapidapi_429_returns_no_data_for_fallback(self):
        coin = {'id': 'a', 'ebay_kw': 'x'}
        with mock.patch.object(prices, 'RAPIDAPI_KEY', 'unit-test-key'), \
             mock.patch.object(prices.urllib.request, 'urlopen', side_effect=OSError('HTTP Error 429')):
            self.assertIsNone(prices._fetch_ebay(coin, timeout=1))

    def test_opt_in_refresh_is_bounded_and_serial(self):
        coins = [
            {'id': f'c{i}', 'search': 'x', 'ebay_kw': 'x'}
            for i in range(6)
        ]
        calls = []
        active = 0
        max_active = 0

        def fake_fetch(coin, timeout):
            nonlocal active, max_active
            calls.append(coin['id'])
            active += 1
            max_active = max(max_active, active)
            time.sleep(0.01)
            active -= 1
            return {'average_price': 20.0, 'products': [{'title': 'fresh'}]}

        with mock.patch.object(prices, 'RAPIDAPI_KEY', 'unit-test-key'), \
             mock.patch.object(prices, 'RAPIDAPI_LIVE_REFRESH', True), \
             mock.patch.object(prices, 'RAPIDAPI_REFRESH_LIMIT', 3), \
             mock.patch.object(prices, '_fetch_ebay', side_effect=fake_fetch), \
             mock.patch.object(prices, '_load_base_cache', return_value={}), \
             mock.patch.object(prices, '_load_manual', return_value={}):
            snapshot, complete = prices._build_payload(coins, deadline=1)

        self.assertTrue(complete)
        self.assertEqual(len(calls), 3)
        self.assertEqual(max_active, 1)
        self.assertEqual(sum(1 for item in snapshot.values() if item['ebay']), 3)


class TestSoldRecordQuality(unittest.TestCase):
    def test_title_quantity_and_date_gate_excludes_mismatches(self):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc).timestamp()
        coin = {'id': 's1_bluey', 'ebay_kw': '2024 $1 Bluey Dollarbuck till coin'}
        products = [
            {'title': '2024 $1 Bluey Dollarbuck Uncirculated Coin', 'sale_price': 12.0,
             'currency': 'AU', 'date_sold': '1 Oct 2026'},
            {'title': 'PAIR of Bingo & Bluey UNC Coins, 2x $1', 'sale_price': 9.95,
             'currency': 'AU', 'date_sold': '2 Oct 2026'},
            {'title': '2023 $1 Bluey Dollarbuck Coin', 'sale_price': 8.0,
             'currency': 'AU', 'date_sold': '2 Oct 2026'},
            {'title': '2024 $1 Bluey Dollarbuck Coin', 'sale_price': 7.0,
             'currency': 'AU', 'date_sold': '1 May 2026'},
        ]
        result = prices._quality_filter_ebay({'products': products}, coin, now=now)
        self.assertEqual([p['sale_price'] for p in result['products']], [12.0])
        self.assertEqual(result['median_price'], 12.0)
        self.assertEqual(result['matched_results'], 1)

    def test_catalogued_multi_coin_set_can_match_its_expected_quantity(self):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc).timestamp()
        coin = {'id': 's1_10_coin_folder_set',
                'ebay_kw': '2024 $1 Bluey ten coin collection folder tube set'}
        record = {'title': '2024 Bluey 10-Coin Collection Folder Tube Set',
                  'sale_price': 80, 'currency': 'AUD', 'date_sold': '1 Oct 2026'}
        self.assertTrue(prices._product_matches_coin(record, coin, now=now))
