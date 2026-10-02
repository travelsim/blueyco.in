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
