import time
import unittest
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
        self.assertEqual(snapshot['c0']['coinxchange']['average_price'], 10.0)
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
        self.assertIsNotNone(snapshot['s1_bluey']['coinxchange'])


if __name__ == '__main__':
    unittest.main()


class TestCoinXchangeDelegation(unittest.TestCase):
    def test_prices_uses_server_sold_parser(self):
        calls = []

        class FakeLegacy:
            @staticmethod
            def _scrape_coinxchange(term, sold_only=True):
                calls.append((term, sold_only))
                return [{'price': 12.0, 'title': 't', 'url': 'u'}]

        with mock.patch.object(prices, '_legacy', return_value=FakeLegacy):
            listings = prices._scrape_coinxchange('Bluey')
        self.assertEqual(calls, [('Bluey', True)])
        self.assertEqual(prices._summarise(listings)['min_price'], 12.0)


class TestPricesRateLimit(unittest.TestCase):
    def setUp(self):
        prices._cache.clear()
        prices._last_fetch.clear()
        prices._last_rapidapi_request = 0.0

    def test_default_path_is_cache_first_when_live_refresh_is_disabled(self):
        coin = {'id': 'a', 'search': 'x', 'ebay_kw': 'x'}
        baseline = {
            'a': {
                'ebay': {'average_price': 12.95, 'products': [{'title': 'cached'}]},
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
        self.assertEqual(snapshot['a']['coinxchange']['average_price'], 10.0)

    def test_429_does_not_replace_cached_ebay(self):
        coin = {'id': 'a', 'search': 'x', 'ebay_kw': 'x'}
        baseline = {
            'a': {
                'ebay': {'average_price': 12.95, 'products': [{'title': 'cached'}]},
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
