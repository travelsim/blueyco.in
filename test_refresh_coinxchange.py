import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from api import prices
from scripts import refresh_coinxchange

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(REPO_ROOT, 'scripts', 'refresh_coinxchange.py')
COIN_A = {'id': 'coin-a', 'ebay_kw': '2024 Bluey coin'}
COIN_B = {'id': 'coin-b', 'ebay_kw': '2024 Bluey coin'}


def days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%d %b %Y')


def coinx_row(price, days=1, title='2024 Bluey coin', **extra):
    """A row in the shape the CoinXchange scraper returns."""
    return {'title': title, 'price': price, 'sold_date': days_ago(days),
            'url': f'https://www.coinxchange.com.au/product/{price}-{days}', **extra}


def offline(testcase):
    """Fail any test that reaches the network instead of mocking it."""
    for target in ('urllib.request.urlopen', 'socket.create_connection'):
        guard = patch(target, side_effect=AssertionError(f'live network call attempted via {target}'))
        guard.start()
        testcase.addCleanup(guard.stop)


class RefreshCoinxchangeTests(unittest.TestCase):
    def setUp(self):
        offline(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache_path = os.path.join(self.temp.name, 'ebay_cache.json')
        self.old_cache = {
            'coin-a': {'ebay': {'products': [{'title': '2024 Bluey coin', 'sale_price': 8.0,
                                              'currency': 'AU', 'date_sold': '1 Jan 2025',
                                              'item_id': 'old-1'}],
                                'historical_products': []}},
            'coin-z': {'ebay': {'products': [], 'historical_products': []}},
        }
        self.write_cache(self.old_cache)

        old_root = refresh_coinxchange.ROOT
        refresh_coinxchange.ROOT = self.temp.name
        self.addCleanup(setattr, refresh_coinxchange, 'ROOT', old_root)
        old_coins = prices.COINS
        prices.COINS = [COIN_A]
        self.addCleanup(setattr, prices, 'COINS', old_coins)

    def write_cache(self, data):
        with open(self.cache_path, 'w', encoding='utf-8') as stream:
            json.dump(data, stream)

    def read_cache(self):
        with open(self.cache_path, encoding='utf-8') as stream:
            return json.load(stream)

    def refresh_with(self, rows, limit=None):
        """Run refresh() with the scraper stubbed; returns the scraper mock and stdout."""
        stdout = io.StringIO()
        with patch.object(prices, '_scrape_coinxchange_all', return_value=rows) as scrape, \
             redirect_stdout(stdout):
            refresh_coinxchange.refresh(limit)
        return scrape, stdout.getvalue()

    def evidence(self, rows, coin_id='coin-a'):
        self.refresh_with(rows)
        return self.read_cache()[coin_id]['coinxchange']

    # Parsing

    def test_query_prefers_ebay_kw_then_search_then_empty(self):
        prices.COINS = [
            {'id': 'coin-a', 'ebay_kw': 'KW term', 'search': 'search term'},
            {'id': 'coin-b', 'search': 'search only'},
            {'id': 'coin-c'},
        ]
        self.refresh_with([])
        cache = self.read_cache()
        self.assertEqual(cache['coin-a']['coinxchange']['search_url'],
                         'https://www.coinxchange.com.au/buy?search=KW+term')
        self.assertEqual(cache['coin-b']['coinxchange']['search_url'],
                         'https://www.coinxchange.com.au/buy?search=search+only')
        self.assertEqual(cache['coin-c']['coinxchange']['search_url'],
                         'https://www.coinxchange.com.au/buy?search=')

    def test_search_url_encodes_dollar_sign_and_spaces(self):
        prices.COINS = [{'id': 'coin-a', 'ebay_kw': '2024 $1 Bluey coin'}]
        self.refresh_with([])
        self.assertEqual(self.read_cache()['coin-a']['coinxchange']['search_url'],
                         'https://www.coinxchange.com.au/buy?search=2024+%241+Bluey+coin')

    def test_scraper_receives_each_catalogue_coin_in_order(self):
        prices.COINS = [COIN_A, COIN_B]
        scrape, _ = self.refresh_with([])
        self.assertEqual([c.args[0] for c in scrape.call_args_list], [COIN_A, COIN_B])

    def test_evidence_counts_candidates_and_matches_and_stamps_fetch_time(self):
        before = datetime.now(timezone.utc).timestamp()
        evidence = self.evidence([
            coinx_row(10.0),
            coinx_row(12.0, title='Unrelated gold sovereign 2024'),
        ])
        self.assertEqual(evidence['source'], 'CoinXchange')
        self.assertEqual(evidence['currency'], 'AUD')
        self.assertEqual(evidence['candidate_results'], 2)
        self.assertEqual(evidence['matched_results'], 1)
        self.assertEqual(evidence['count'], 1)
        self.assertGreaterEqual(evidence['fetchedAt'], before)
        self.assertLessEqual(evidence['fetchedAt'], datetime.now(timezone.utc).timestamp())

    def test_progress_line_and_summary_are_printed(self):
        prices.COINS = [COIN_A, COIN_B]
        _, output = self.refresh_with([coinx_row(10.0)])
        self.assertIn('1/2 coin-a: 1 matched of 1 candidate sold records', output)
        self.assertIn('2/2 coin-b: 1 matched of 1 candidate sold records', output)
        self.assertIn(f'Updated 2 CoinXchange snapshots in {self.cache_path}', output)

    # Quality gates

    def test_titles_that_do_not_match_the_coin_are_counted_but_not_kept(self):
        evidence = self.evidence([coinx_row(10.0, title='Unrelated gold sovereign 2024')])
        self.assertEqual(evidence['candidate_results'], 1)
        self.assertEqual(evidence['matched_results'], 0)
        self.assertEqual(evidence['products'], [])
        self.assertIsNone(evidence['median_price'])

    def test_sales_older_than_90_days_go_to_history_not_the_median(self):
        evidence = self.evidence([coinx_row(10.0, days=1), coinx_row(50.0, days=200)])
        self.assertEqual([p['price'] for p in evidence['products']], [10.0])
        self.assertEqual([p['price'] for p in evidence['historical_products']], [50.0])
        self.assertEqual(evidence['median_price'], 10.0)

    def test_median_and_average_over_recent_sales(self):
        odd = self.evidence([coinx_row(8.0, days=1), coinx_row(12.0, days=2), coinx_row(10.0, days=3)])
        self.assertEqual((odd['min_price'], odd['median_price'], odd['max_price'], odd['average_price']),
                         (8.0, 10.0, 12.0, 10.0))
        even = self.evidence([coinx_row(8.0, days=1), coinx_row(12.0, days=2),
                              coinx_row(10.0, days=3), coinx_row(20.0, days=4)])
        self.assertEqual(even['median_price'], 11.0)

    def test_non_aud_currency_is_rejected_and_missing_currency_defaults_to_aud(self):
        evidence = self.evidence([
            coinx_row(10.0, days=1, currency='USD'),
            coinx_row(11.0, days=2),
        ])
        self.assertEqual([p['price'] for p in evidence['products']], [11.0])

    def test_absurd_price_is_excluded_as_an_outlier(self):
        evidence = self.evidence([coinx_row(1000000.0, days=1), coinx_row(10.0, days=2)])
        self.assertEqual([p['price'] for p in evidence['products']], [10.0])

    def test_duplicate_rows_are_counted_once(self):
        row = coinx_row(10.0, days=1)
        evidence = self.evidence([row, dict(row)])
        self.assertEqual(evidence['candidate_results'], 2)
        self.assertEqual(evidence['matched_results'], 1)

    def test_unparseable_zero_and_negative_prices_are_dropped(self):
        evidence = self.evidence([
            coinx_row('N/A', days=1),
            coinx_row(0, days=2),
            coinx_row(-5.0, days=3),
            coinx_row(10.0, days=4),
        ])
        self.assertEqual([p['price'] for p in evidence['products']], [10.0])

    def test_non_dict_rows_are_skipped_without_crashing(self):
        evidence = self.evidence([None, 'junk', coinx_row(10.0, days=1)])
        self.assertEqual(evidence['candidate_results'], 3)
        self.assertEqual(evidence['matched_results'], 1)

    def test_other_coins_and_sources_are_preserved(self):
        prices.COINS = [COIN_A]
        self.refresh_with([coinx_row(10.0, days=1)])
        cache = self.read_cache()
        self.assertEqual(cache['coin-a']['ebay'], self.old_cache['coin-a']['ebay'])
        self.assertEqual(cache['coin-z'], self.old_cache['coin-z'])
        self.assertIn('coinxchange', cache['coin-a'])

    # Error paths

    def test_failed_request_stops_without_saving_or_replacing_the_cache(self):
        with patch.object(prices, '_scrape_coinxchange_all', return_value=None), \
             patch.object(refresh_coinxchange.os, 'replace') as replace:
            with self.assertRaisesRegex(RuntimeError, 'CoinXchange request failed for coin-a; stopping without saving'):
                refresh_coinxchange.refresh()
        replace.assert_not_called()
        self.assertEqual(self.read_cache(), self.old_cache)

    def test_failure_on_a_later_coin_writes_nothing(self):
        prices.COINS = [COIN_A, COIN_B]
        with patch.object(prices, '_scrape_coinxchange_all', side_effect=[[coinx_row(10.0)], None]), \
             redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'coin-b'):
                refresh_coinxchange.refresh()
        self.assertEqual(self.read_cache(), self.old_cache)
        self.assertEqual(os.listdir(self.temp.name), ['ebay_cache.json'])

    def test_missing_cache_file_fails_before_any_request(self):
        os.remove(self.cache_path)
        with patch.object(prices, '_scrape_coinxchange_all') as scrape:
            with self.assertRaises(FileNotFoundError):
                refresh_coinxchange.refresh()
        scrape.assert_not_called()

    def test_corrupt_cache_file_fails_before_any_request(self):
        with open(self.cache_path, 'w', encoding='utf-8') as stream:
            stream.write('not json')
        with patch.object(prices, '_scrape_coinxchange_all') as scrape:
            with self.assertRaises(json.JSONDecodeError):
                refresh_coinxchange.refresh()
        scrape.assert_not_called()

    def test_write_failure_removes_temp_file_and_keeps_old_cache(self):
        with patch.object(refresh_coinxchange.os, 'replace', side_effect=OSError('disk full')), \
             patch.object(prices, '_scrape_coinxchange_all', return_value=[coinx_row(10.0)]), \
             redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(OSError, 'disk full'):
                refresh_coinxchange.refresh()
        self.assertEqual(self.read_cache(), self.old_cache)
        self.assertEqual(os.listdir(self.temp.name), ['ebay_cache.json'])

    def test_serialisation_failure_removes_temp_file_and_keeps_old_cache(self):
        bad_evidence = {'matched_results': 0, 'candidate_results': 0, 'unserialisable': object()}
        with patch.object(prices, '_quality_filter_coinxchange', return_value=bad_evidence), \
             patch.object(prices, '_scrape_coinxchange_all', return_value=[]), \
             redirect_stdout(io.StringIO()):
            with self.assertRaises(TypeError):
                refresh_coinxchange.refresh()
        self.assertEqual(self.read_cache(), self.old_cache)
        self.assertEqual(os.listdir(self.temp.name), ['ebay_cache.json'])

    def test_temp_cleanup_failure_still_raises_the_original_error(self):
        with patch.object(refresh_coinxchange.os, 'replace', side_effect=OSError('replace failed')), \
             patch.object(refresh_coinxchange.os, 'unlink', side_effect=OSError('unlink failed')), \
             patch.object(prices, '_scrape_coinxchange_all', return_value=[]), \
             redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(OSError, 'replace failed'):
                refresh_coinxchange.refresh()


class RefreshCoinxchangeEntryPointTests(unittest.TestCase):
    """Runs the real script as __main__. Its ROOT is derived from __file__, so that is
    pointed at a temp tree; the code is compiled with the real path so coverage counts it."""

    def setUp(self):
        offline(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with open(SCRIPT_PATH, encoding='utf-8') as stream:
            self.source = stream.read()
        self.fake_script_file = os.path.join(self.temp.name, 'scripts', 'refresh_coinxchange.py')
        self.cache_path = os.path.join(self.temp.name, 'ebay_cache.json')
        self.old_cache = {'coin-a': {'ebay': {'products': []}}}
        with open(self.cache_path, 'w', encoding='utf-8') as stream:
            json.dump(self.old_cache, stream)
        old_coins = prices.COINS
        prices.COINS = [COIN_A, COIN_B]
        self.addCleanup(setattr, prices, 'COINS', old_coins)
        old_path = list(sys.path)
        self.addCleanup(setattr, sys, 'path', old_path)

    def execute_main(self):
        exec(compile(self.source, SCRIPT_PATH, 'exec'),
             {'__name__': '__main__', '__file__': self.fake_script_file})

    def run_cli(self, argv, rows=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(prices, '_scrape_coinxchange_all', return_value=rows) as scrape, \
             patch.object(sys, 'argv', ['refresh_coinxchange.py', *argv]), \
             redirect_stdout(stdout), redirect_stderr(stderr):
            self.execute_main()
        return scrape, stdout.getvalue(), stderr.getvalue()

    def read_cache(self):
        with open(self.cache_path, encoding='utf-8') as stream:
            return json.load(stream)

    def test_cli_refreshes_every_coin_and_writes_the_cache(self):
        scrape, output, _ = self.run_cli([], rows=[coinx_row(10.0)])
        self.assertEqual(scrape.call_count, 2)
        self.assertIn('1/2 coin-a', output)
        self.assertIn('2/2 coin-b', output)
        self.assertIn('Updated 2 CoinXchange snapshots', output)
        cache = self.read_cache()
        self.assertIn('coinxchange', cache['coin-a'])
        self.assertIn('coinxchange', cache['coin-b'])

    def test_cli_limit_refreshes_only_the_first_n_entries(self):
        scrape, output, _ = self.run_cli(['--limit', '1'], rows=[coinx_row(10.0)])
        self.assertEqual([c.args[0]['id'] for c in scrape.call_args_list], ['coin-a'])
        self.assertIn('Updated 1 CoinXchange snapshots', output)
        self.assertNotIn('coin-b', self.read_cache())

    def run_cli_expecting_usage_error(self, limit_value):
        stderr = io.StringIO()
        with patch.object(prices, '_scrape_coinxchange_all', return_value=[]) as scrape, \
             patch.object(sys, 'argv', ['refresh_coinxchange.py', '--limit', limit_value]), \
             redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as exit_info:
                self.execute_main()
        self.assertEqual(exit_info.exception.code, 2)
        scrape.assert_not_called()
        self.assertEqual(self.read_cache(), self.old_cache)
        return stderr.getvalue()

    def test_cli_rejects_a_zero_limit_before_any_request(self):
        self.assertIn('--limit must be at least 1', self.run_cli_expecting_usage_error('0'))

    def test_cli_rejects_a_non_integer_limit(self):
        self.assertIn('invalid int value', self.run_cli_expecting_usage_error('ten'))

    def test_cli_request_failure_propagates_and_writes_nothing(self):
        with self.assertRaisesRegex(RuntimeError, 'without saving'):
            self.run_cli([], rows=None)
        self.assertEqual(self.read_cache(), self.old_cache)
        self.assertEqual(os.listdir(self.temp.name), ['ebay_cache.json'])


if __name__ == '__main__':
    unittest.main()
