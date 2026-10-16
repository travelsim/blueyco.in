"""Tests for the serverless EPN affiliate fix and upstream-failure fallback.

Covers: one safe affiliate wrapper on every serverless eBay URL path
(manual search URLs, live product URLs, buy-options URLs) with
enabled/disabled tagging, no double-tagging, and preserved query
parameters/encoding; plus honest fallback when the RapidAPI upstream
returns 429/403 or times out (cached snapshot preserved, HTTP 200 shape).
"""
import importlib.util
import json
import os
import unittest
import urllib.error
from unittest import mock

import server as legacy
from api import prices

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    'buy_options', os.path.join(_ROOT, 'api', 'buy-options.py')
)
buy_options = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(buy_options)


class TestAffiliateDoubleTag(unittest.TestCase):
    def setUp(self):
        self._orig = legacy.EPN_CAMPAIGN_ID
        legacy.EPN_CAMPAIGN_ID = 'testcamp'

    def tearDown(self):
        legacy.EPN_CAMPAIGN_ID = self._orig

    def test_already_tagged_url_returned_unchanged(self):
        once = legacy.affiliate_url('https://www.ebay.com.au/itm/12345',
                                    coin_id='s1_bluey', source='ebay_sold')
        self.assertEqual(once.count('campid='), 1)
        self.assertEqual(legacy.affiliate_url(once, coin_id='s1_bluey'), once)

    def test_prices_wrapper_never_double_tags(self):
        with mock.patch.dict(os.environ, {'EPN_CAMPAIGN_ID': 'testcamp'}):
            once = prices._affiliate_url('https://www.ebay.com.au/itm/12345',
                                         coin_id='s1_bluey', source='ebay_sold')
            self.assertEqual(once.count('campid='), 1)
            self.assertEqual(prices._affiliate_url(once, coin_id='s1_bluey'), once)


class TestPricesAffiliateWrapper(unittest.TestCase):
    def test_disabled_leaves_valid_ordinary_urls(self):
        with mock.patch.dict(os.environ, {'EPN_CAMPAIGN_ID': ''}):
            search = ('https://www.ebay.com.au/sch/i.html?'
                      '_nkw=2024+Bluey+Dollarbuck+Bluey&LH_Sold=1&_sop=15')
            product = 'https://www.ebay.com.au/itm/198341345495?_skw=2024+%241+Bluey'
            self.assertEqual(prices._affiliate_url(search, coin_id='s1_bluey'), search)
            self.assertEqual(prices._affiliate_url(product, coin_id='s1_bluey'), product)

    def test_enabled_tags_and_preserves_params_and_encoding(self):
        with mock.patch.dict(os.environ, {'EPN_CAMPAIGN_ID': 'testcamp'}):
            search = ('https://www.ebay.com.au/sch/i.html?'
                      '_nkw=2024+Bluey+Dollarbuck+Bluey&LH_Sold=1&_sop=15')
            tagged = prices._affiliate_url(search, coin_id='s1_bluey',
                                           source='ebay_search')
            self.assertIn('&campid=testcamp', tagged)
            self.assertIn('&mkcid=1', tagged)
            self.assertIn('customid=5339153744', tagged)
            # Original query parameters and percent-encoding survive intact.
            self.assertIn('_nkw=2024+Bluey+Dollarbuck+Bluey', tagged)
            self.assertIn('LH_Sold=1', tagged)
            encoded = 'https://www.ebay.com.au/itm/1?_skw=2026+%242+Bluey+%2F+Rain'
            tagged_product = prices._affiliate_url(encoded, coin_id='s3_rain')
            self.assertIn('%242', tagged_product)
            self.assertIn('%2F', tagged_product)

    def test_legacy_url_gains_mkcid(self):
        with mock.patch.dict(os.environ, {'EPN_CAMPAIGN_ID': 'testcamp'}):
            legacy_url = 'https://www.ebay.com.au/itm/12345?campid=testcamp&mkevt=1'
            tagged = prices._affiliate_url(legacy_url, coin_id='s1_bluey')
            self.assertIn('mkcid=1', tagged)
            self.assertEqual(prices._affiliate_url(tagged, coin_id='s1_bluey'), tagged)

    def test_non_ebay_and_empty_untouched(self):
        with mock.patch.dict(os.environ, {'EPN_CAMPAIGN_ID': 'testcamp'}):
            cx = 'https://www.coinxchange.com.au/buy?search=Bluey'
            self.assertEqual(prices._affiliate_url(cx), cx)
            self.assertEqual(prices._affiliate_url(''), '')
            self.assertIsNone(prices._affiliate_url(None))


class TestPricesSnapshotTagging(unittest.TestCase):
    def setUp(self):
        prices._cache.clear()
        prices._last_fetch.clear()

    def _baseline(self):
        return {
            's1_bluey': {
                'ebay': {
                    'average_price': 12.95,
                    'response_url': ('https://www.ebay.com.au/sch/9355/i.html?'
                                     '_nkw=Bluey&LH_Sold=1&_ipg=60'),
                    'products': [{'title': 'x', 'sale_price': 12.95,
                                  'currency': 'AU', 'date_sold': '1 Oct 2026',
                                  'link': 'https://www.ebay.com.au/itm/111'}],
                },
                'coinxchange': {'average_price': 10.0},
            }
        }

    def _manual(self):
        return {'s1_bluey': {'ebay': {
            'price': None,
            'url': ('https://www.ebay.com.au/sch/i.html?'
                    '_nkw=2024+Bluey&LH_Sold=1&_sop=15'),
        }}}

    def _snapshot(self, coins):
        with mock.patch.object(prices, '_load_base_cache', return_value=self._baseline()), \
             mock.patch.object(prices, '_load_manual', return_value=self._manual()), \
             mock.patch.object(prices, '_load_manual_ebay_sales', return_value={}):
            snapshot, complete = prices._build_payload(coins, deadline=1)
        return snapshot, complete

    def test_snapshot_tags_ebay_urls_when_campaign_configured(self):
        coins = [{'id': 's1_bluey', 'search': 'x', 'ebay_kw': 'x'}]
        with mock.patch.dict(os.environ, {'EPN_CAMPAIGN_ID': 'testcamp'}):
            snapshot, _ = self._snapshot(coins)
        entry = snapshot['s1_bluey']
        self.assertIn('campid=testcamp', entry['ebay']['response_url'])
        self.assertIn('LH_Sold=1', entry['ebay']['response_url'])
        self.assertIn('campid=testcamp', entry['ebay']['products'][0]['link'])
        self.assertIn('campid=testcamp', entry['manual']['ebay']['url'])
        # Historical CoinXchange scrape data is no longer served.
        self.assertIsNone(entry['coinxchange'])

    def test_snapshot_leaves_ordinary_urls_when_no_campaign(self):
        coins = [{'id': 's1_bluey', 'search': 'x', 'ebay_kw': 'x'}]
        with mock.patch.dict(os.environ, {'EPN_CAMPAIGN_ID': ''}):
            snapshot, _ = self._snapshot(coins)
        entry = snapshot['s1_bluey']
        self.assertNotIn('campid=', entry['ebay']['response_url'])
        self.assertNotIn('campid=', entry['ebay']['products'][0]['link'])
        self.assertNotIn('campid=', entry['manual']['ebay']['url'])
        self.assertTrue(entry['ebay']['response_url'].startswith('https://www.ebay.com.au'))

    def test_snapshot_tagging_is_idempotent(self):
        coins = [{'id': 's1_bluey', 'search': 'x', 'ebay_kw': 'x'}]
        with mock.patch.dict(os.environ, {'EPN_CAMPAIGN_ID': 'testcamp'}):
            snapshot, _ = self._snapshot(coins)
            retagged = prices._tag_ebay_urls(snapshot['s1_bluey']['ebay'], 's1_bluey')
        self.assertEqual(retagged['response_url'].count('campid='), 1)
        self.assertEqual(retagged['products'][0]['link'].count('campid='), 1)

    def test_every_catalogue_coin_gets_a_live_affiliate_sold_search(self):
        with mock.patch.dict(os.environ, {'EPN_CAMPAIGN_ID': 'testcamp'}):
            snapshot = prices._cached_snapshot(prices.COINS, {}, {})
        self.assertEqual(len(snapshot), len(prices.COINS))
        for coin_id, entry in snapshot.items():
            url = entry['manual']['ebay']['url']
            self.assertIn('LH_Sold=1', url, coin_id)
            self.assertIn('LH_Complete=1', url, coin_id)
            self.assertIn('campid=testcamp', url, coin_id)


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestUpstreamFailureFallback(unittest.TestCase):
    def setUp(self):
        prices._cache.clear()
        prices._last_fetch.clear()
        prices._last_rapidapi_request = 0.0

    def _fetch_with_urlopen(self, side_effect):
        coin = {'id': 'a', 'ebay_kw': 'x'}
        with mock.patch.object(prices, 'RAPIDAPI_KEY', 'unit-test-key'), \
             mock.patch.object(prices.urllib.request, 'urlopen', side_effect=side_effect):
            return prices._fetch_ebay(coin, timeout=1)

    def test_403_returns_no_data_for_fallback(self):
        err = urllib.error.HTTPError('https://x.test', 403, 'Forbidden', {}, None)
        self.assertIsNone(self._fetch_with_urlopen(err))

    def test_timeout_returns_no_data_for_fallback(self):
        self.assertIsNone(self._fetch_with_urlopen(TimeoutError('timed out')))

    def test_fresh_product_links_are_tagged(self):
        payload = {'products': [{'title': 't', 'link': 'https://www.ebay.com.au/itm/222'}],
                   'average_price': 20.0, 'total_results': 3}
        coin = {'id': 'a', 'ebay_kw': 'x'}
        with mock.patch.object(prices, 'RAPIDAPI_KEY', 'unit-test-key'), \
             mock.patch.object(prices.urllib.request, 'urlopen',
                               return_value=FakeResp(payload)), \
             mock.patch.dict(os.environ, {'EPN_CAMPAIGN_ID': 'testcamp'}):
            prices._last_rapidapi_request = 0.0
            result = prices._fetch_ebay(coin, timeout=1)
        self.assertIn('campid=testcamp', result['products'][0]['link'])
        self.assertEqual(result['average_price'], 20.0)

    def test_error_payload_preserves_cached_snapshot_and_shape(self):
        coin = {'id': 'a', 'search': 'x', 'ebay_kw': 'x'}
        baseline = {'a': {'ebay': {'average_price': 12.95,
                                   'products': [{'title': 'x', 'sale_price': 12.95,
                                                 'currency': 'AU', 'date_sold': '1 Oct 2026'}]},
                          'coinxchange': {'average_price': 10.0}}}

        def fetch(_coin):
            return {'ebay': {'error': 'HTTP Error 403: Forbidden',
                             'average_price': None, 'products': []},
                    'coinxchange': None}

        with mock.patch.object(prices, '_load_base_cache', return_value=baseline), \
             mock.patch.object(prices, '_load_manual', return_value={}):
            snapshot, _ = prices._build_payload([coin], fetch_coin=fetch, deadline=1)
        # Cached price survives; error never appears as a fresh price.
        self.assertEqual(snapshot['a']['ebay']['average_price'], 12.95)
        self.assertIsNone(snapshot['a']['coinxchange'])
        # Honest response shape is unchanged: every coin carries all three keys.
        self.assertEqual(set(snapshot['a'].keys()), {'ebay', 'coinxchange', 'manual'})


class TestBuyOptionsFallbackTagging(unittest.TestCase):
    def setUp(self):
        self._orig = legacy.EPN_CAMPAIGN_ID
        buy_options._cache.clear()

    def tearDown(self):
        legacy.EPN_CAMPAIGN_ID = self._orig

    def _ebay_retailer(self):
        return [r for r in legacy.RETAILERS if r['id'] == 'ebay'][0]

    def test_manual_ebay_url_tagged_when_campaign_configured(self):
        legacy.EPN_CAMPAIGN_ID = 'testcamp'
        manual = {'s1_bluey': {'ebay': {
            'price': None,
            'url': 'https://www.ebay.com.au/sch/i.html?_nkw=Bluey&LH_Sold=1&_sop=15'}}}
        option = buy_options._fallback(self._ebay_retailer(), 'Bluey', 's1_bluey', manual)[0]
        # Hand-written manual eBay URLs are ignored; the link is generated from
        # the coin's own query and still affiliate-tagged.
        self.assertIn('campid=testcamp', option['url'])
        self.assertNotIn('LH_Sold=1', option['url'])
        self.assertIn('customid=5339153744', option['url'])
        self.assertTrue(option['link_only'])

    def test_manual_ebay_url_untagged_without_campaign(self):
        legacy.EPN_CAMPAIGN_ID = ''
        raw = 'https://www.ebay.com.au/sch/i.html?_nkw=Bluey&LH_Sold=1&_sop=15'
        manual = {'s1_bluey': {'ebay': {'price': None, 'url': raw}}}
        option = buy_options._fallback(self._ebay_retailer(), 'Bluey', 's1_bluey', manual)[0]
        self.assertNotEqual(option['url'], raw)
        self.assertNotIn('LH_Sold=1', option['url'])
        self.assertNotIn('campid=', option['url'])

    def test_non_ebay_manual_url_never_tagged(self):
        legacy.EPN_CAMPAIGN_ID = 'testcamp'
        coinxchange = [r for r in legacy.RETAILERS if r['id'] == 'coinxchange_buy'][0]
        manual = {'s1_bluey': {'coinxchange_buy': {
            'price': 20.0, 'url': 'https://www.coinxchange.com.au/buy?search=Bluey'}}}
        option = buy_options._fallback(coinxchange, 'Bluey', 's1_bluey', manual)[0]
        self.assertEqual(option['url'], 'https://www.coinxchange.com.au/buy?search=Bluey')


if __name__ == '__main__':
    unittest.main()
