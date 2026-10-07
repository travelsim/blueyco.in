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
        # CoinXchange is disabled (no scraper, no link-only fallback) pending James's direct permission.
        for r in legacy.RETAILERS:
            if r['id'] == 'coinxchange_buy':
                continue
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
        manual = {'s1_bluey': {'coinxchange_buy': {
            'price': 42.0, 'checkedAt': time.time(),
            'url': 'https://example.test/bluey',
        }}}
        original = buy_options._manual
        buy_options._manual = lambda: manual
        try:
            retailer = next(r for r in legacy.RETAILERS if r['id'] == 'coinxchange_buy')
            option = buy_options._fallback(retailer, '2024 Bluey', 's1_bluey', manual)[0]
        finally:
            buy_options._manual = original
        self.assertEqual(option['price'], 42.0)
        self.assertEqual(option['url'], 'https://example.test/bluey')
        self.assertFalse(option['link_only'])
        self.assertEqual(option['price_type'], 'asking')

    def test_gumtree_remains_search_only_and_resellers_are_gone(self):
        retailers = {r['id']: r for r in legacy.RETAILERS}
        for retailer_id in ('gumtree',):
            retailer = retailers[retailer_id]
            self.assertEqual(retailer['type'], 'link_only')
            with mock.patch.object(legacy, '_http_get', side_effect=AssertionError('network access')):
                self.assertEqual(buy_options._scrape(retailer, '2024 Bluey coin', 's1_bluey'), [])
            option = buy_options._fallback(retailer, '2024 Bluey coin', 's1_bluey', {})[0]
            self.assertTrue(option['link_only'])
            self.assertIsNone(option['price'])
            self.assertIn('2024', option['url'])
        for removed in ('cashconverters', 'nova_coins', 'aussie_coins_direct'):
            self.assertNotIn(removed, retailers)

    def test_browse_query_is_plain_keywords_not_the_long_exclusion_query(self):
        # eBay's Browse 'q' is length-limited; the long -(...) query 400'd in production.
        retailer = {r['id']: r for r in legacy.RETAILERS}['ebay']
        seen = []
        def fake(q, limit=5):
            seen.append(q)
            return []
        with mock.patch.object(legacy, '_ebay_browse_search', side_effect=fake):
            legacy._ebay_live_options(retailer, '2024 $1 Bluey Dollarbuck Bluey coin uncirculated', 's1_bluey')
        self.assertEqual(seen, ['2024 $1 Bluey Dollarbucks Bluey uncirculated'])

    def test_till_coin_query_drops_till_and_matches_plural_titles(self):
        retailer = {r['id']: r for r in legacy.RETAILERS}['ebay']
        raw = [{'title': '2024 Bluey $1 Dollarbucks Uncirculated Coin RAM', 'price': 4.5, 'url': 'https://www.ebay.com.au/itm/1'},
               {'title': '2024 Bluey $1 Dollarbucks Proof Coin', 'price': 600.0, 'url': 'https://www.ebay.com.au/itm/2'},
               {'title': '2024 Bingo $1 Dollarbucks Uncirculated', 'price': 5.0, 'url': 'https://www.ebay.com.au/itm/3'}]
        seen = []
        def fake(q, limit=5):
            seen.append(q)
            return raw
        with mock.patch.object(legacy, '_ebay_browse_search', side_effect=fake):
            out = legacy._ebay_live_options(retailer, '2024 $1 Bluey Dollarbuck till coin', 's1_bluey')
        self.assertEqual(seen, ['2024 $1 Bluey Dollarbucks'])
        self.assertEqual([o['price'] for o in out], [4.5])

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

    def test_ebay_live_offer_keeps_title_price_label_and_affiliate_link(self):
        retailer = {r['id']: r for r in legacy.RETAILERS}['ebay']
        listing = {
            'price': 12.5,
            'title': '2024 Bluey Dollarbuck till coin - uncirculated',
            'url': 'https://www.ebay.com.au/itm/12345',
            'subtitle': 'Uncirculated',
        }
        with mock.patch.object(legacy, 'EPN_CAMPAIGN_ID', 'test-campaign'):
            with mock.patch.object(legacy, '_ebay_browse_search', return_value=[listing]):
                with mock.patch.object(legacy, '_ebay_rapidapi_search') as fallback:
                    option = legacy._ebay_live_options(retailer, '2024 Bluey Dollarbuck till coin', 's1_bluey')[0]
                    fallback.assert_not_called()
        self.assertEqual(option['title'], listing['title'])
        self.assertEqual(option['price'], 12.5)
        self.assertEqual(option['price_type'], 'asking')
        self.assertFalse(option['link_only'])
        self.assertIn('campid=', option['url'])

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

    def test_search_and_ebay_keywords_are_one_uniform_description(self):
        legacy_by_id = legacy.COIN_BY_ID
        for coin in prices.COINS:
            self.assertEqual(coin['search'], coin['ebay_kw'], coin['id'])
            self.assertEqual(legacy_by_id[coin['id']]['ebay_kw'], coin['ebay_kw'], coin['id'])
            self.assertEqual(legacy_by_id[coin['id']]['search'], coin['search'], coin['id'])

    def test_cricket_proof_and_uncirculated_are_not_cross_polluted(self):
        unc = legacy.COIN_BY_ID['s4_cricket_unc']['search']
        proof = legacy.COIN_BY_ID['s4_cricket_proof']['search']
        unc_title = '2027 Bluey Cricket $1 Coloured Uncirculated Coin'
        proof_title = '2027 Bluey Cricket $1 Coloured Silver Proof Coin'
        self.assertTrue(legacy._coinxchange_title_matches(unc_title, unc))
        self.assertFalse(legacy._coinxchange_title_matches(proof_title, unc))
        self.assertTrue(legacy._coinxchange_title_matches(proof_title, proof))
        self.assertFalse(legacy._coinxchange_title_matches(unc_title, proof))
        for record_title, query in ((unc_title, proof), (proof_title, unc)):
            record = {'title': record_title, 'sale_price': 30, 'currency': 'AUD', 'date_sold': '1 Oct 2026'}
            now = time.mktime((2026, 10, 5, 0, 0, 0, 0, 0, 0))
            self.assertFalse(prices._product_matches_coin(record, {'ebay_kw': query}, now=now))

    def test_ebay_query_excludes_other_formats_and_characters(self):
        query = legacy._ebay_query('2027 $1 Bluey Cricket coloured uncirculated coin')
        self.assertTrue(query.startswith('2027 $1 Bluey Cricket coloured uncirculated coin -('))
        self.assertIn('proof', query)
        self.assertIn('bingo', query)
        self.assertNotIn('cricket,', query.split(' -(')[1])
        sleepy = legacy._ebay_query('2026 $2 Bluey Sleepytime privy mark uncirculated')
        self.assertNotIn('sleepy', sleepy.split(' -(')[1])
        self.assertNotIn('privy', sleepy.split(' -(')[1])

    def test_ebay_live_offers_drop_unrelated_cheap_listings(self):
        retailer = {r['id']: r for r in legacy.RETAILERS}['ebay']
        listings = [
            {'price': 3.0, 'title': '2027 Bluey Cricket sticker sheet', 'url': 'https://www.ebay.com.au/itm/1'},
            {'price': 20.0, 'title': '2027 Bluey Cricket $1 Coloured Silver Proof Coin', 'url': 'https://www.ebay.com.au/itm/2'},
            {'price': 40.0, 'title': '2027 Bluey Cricket $1 Coloured Uncirculated Coin', 'url': 'https://www.ebay.com.au/itm/3'},
        ]
        keywords = legacy.COIN_BY_ID['s4_cricket_unc']['search']
        with mock.patch.object(legacy, '_ebay_browse_search', return_value=listings):
            options = legacy._ebay_live_options(retailer, keywords, 's4_cricket_unc')
        self.assertEqual([o['price'] for o in options], [40.0])


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
