import importlib.util
import json
import os
import re
import tempfile
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

    def test_neon_projection_is_merged_and_reported(self):
        from api import active_offers

        class Conn:
            def __enter__(self): return self
            def __exit__(self, *args): return False

        stored_row = ('999999999999', 'Stored Bluey listing', 42.5, 6.5,
                      'https://www.ebay.com.au/itm/999999999999', 'ebay')
        with mock.patch.dict(os.environ, {'DATABASE_URL': 'postgresql://example/bluey'}), \
                mock.patch.object(active_offers, 'connect', return_value=Conn()), \
                mock.patch.object(active_offers, 'current_offers', return_value=[stored_row]):
            options, _ = buy_options.get_buy_options('s1_bluey', '2024 Bluey Dollarbuck Bluey')
        merged = [o for o in options if o.get('offer_source') == 'active_offers']
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['price'], 42.5)
        self.assertEqual(merged[0]['url'], stored_row[4])
        self.assertEqual(buy_options._projection['s1_bluey'],
                         {'source': 'active_offers', 'stored': 1})

    def test_priced_options_sort_before_link_only(self):
        options, _ = buy_options.get_buy_options('s1_bluey', '2024 Bluey Dollarbuck Bluey')
        seen_link_only = False
        for o in options:
            if o.get('link_only') or o.get('price') is None:
                seen_link_only = True
            else:
                self.assertFalse(seen_link_only, 'priced option after a link-only option')

    def test_ebay_manual_item_override_is_honoured(self):
        manual = {'76604959': {'ebay': {
            'price': 191.53, 'checkedAt': time.time(),
            'url': 'https://www.ebay.com.au/itm/820389839352',
        }}}
        retailer = next(r for r in legacy.RETAILERS if r['id'] == 'ebay')
        option = buy_options._fallback(retailer, '2026 Bluey three coin PNC', '76604959', manual)[0]
        self.assertEqual(option['price'], 191.53)
        self.assertFalse(option['link_only'])
        self.assertIn('itm/820389839352', option['url'])
        self.assertEqual(option['price_type'], 'asking')

    def test_ebay_manual_stale_price_falls_back_to_link_only(self):
        manual = {'76604959': {'ebay': {
            'price': 191.53, 'checkedAt': time.time() - 8 * 24 * 3600,
            'url': 'https://www.ebay.com.au/itm/820389839352',
        }}}
        retailer = next(r for r in legacy.RETAILERS if r['id'] == 'ebay')
        option = buy_options._fallback(retailer, '2026 Bluey three coin PNC', '76604959', manual)[0]
        self.assertIsNone(option['price'])
        self.assertTrue(option['link_only'])

    def test_manual_asking_row_carries_subtitle_and_free_postage(self):
        # A live Buy It Now row keeps its own label and a real delivered total.
        manual = {'s1_impressions_pnc_silver': {'ebay': {
            'price': 2799.98, 'postage': 0, 'checkedAt': time.time(),
            'subtitle': 'Live Buy It Now · checked 2026-11-27',
            'url': 'https://www.ebay.com.au/itm/167880929655',
        }}}
        retailer = next(r for r in legacy.RETAILERS if r['id'] == 'ebay')
        option = buy_options._fallback(retailer, '2024 Bluey silver proof PNC', 's1_impressions_pnc_silver', manual)[0]
        self.assertEqual(option['price'], 2799.98)
        self.assertEqual(option['postage'], 0.0)
        self.assertEqual(option['subtitle'], 'Live Buy It Now · checked 2026-11-27')
        self.assertFalse(option['link_only'])
        self.assertIn('itm/167880929655', option['url'])

    def test_ebay_search_link_entry_is_not_used(self):
        manual = {'s1_bluey': {'ebay': {
            'price': None, 'available': True,
            'url': 'https://www.ebay.com.au/sch/i.html?_nkw=x&LH_BIN=1',
        }}}
        retailer = next(r for r in legacy.RETAILERS if r['id'] == 'ebay')
        option = buy_options._fallback(retailer, '2024 Bluey', 's1_bluey', manual)[0]
        self.assertTrue(option['link_only'])
        self.assertIn('sch/i.html', option['url'])

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

    def test_gumtree_and_resellers_are_gone_coinxchange_is_kept(self):
        retailers = {r['id']: r for r in legacy.RETAILERS}
        for removed in ('gumtree', 'cashconverters', 'nova_coins', 'aussie_coins_direct'):
            self.assertNotIn(removed, retailers)
        self.assertEqual(retailers['coinxchange_buy']['type'], 'coinxchange')

    def test_coinxchange_listings_reach_the_buy_panel(self):
        raw = [{'price': 30.0, 'title': '2024 Bluey Dollarbuck till coin',
                'url': 'https://www.coinxchange.com.au/buy/abc', 'currency': 'AUD', 'seller': 's'}]
        retailer = {r['id']: r for r in legacy.RETAILERS}['coinxchange_buy']
        with mock.patch.object(legacy, '_scrape_coinxchange', return_value=raw):
            options = buy_options._scrape(retailer, '2024 Bluey Dollarbuck till coin', 's1_bluey')
        self.assertEqual(options[0]['retailer_id'], 'coinxchange_buy')
        self.assertEqual(options[0]['price'], 30.0)
        self.assertEqual(options[0]['price_type'], 'asking')

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

    def test_coinxchange_matcher_accepts_real_till_coin_titles_and_rejects_bundles(self):
        k = legacy._browse_keywords('till coin 2026 coloured')
        for title in ('2026 $2 Bluey Till Coin - CIRC',
                      '2026 $2 Bluey For Real Life Coloured Coin aUnc'):
            self.assertTrue(legacy._coinxchange_title_matches(title, k, True), title)
        bingo = legacy._browse_keywords('till coin 2026 bingo')
        self.assertTrue(legacy._coinxchange_title_matches(
            '2026 BLUEY BINGO HOORAY $2 COLOURED UNCIRCULATED COIN', bingo, True))
        for title in ('2026 Winter Olympic $2 Coloured Coin',
                      '2026 $2 Bluey Bingo Till Coin Set',
                      '2026 Bluey Tube & Folder Set + 2 Till Coins',
                      '2024 $1 Bluey Dollarbucks- Bingo ENVELOPE Privymark Carded Coin'):
            self.assertFalse(legacy._coinxchange_title_matches(title, bingo, True), title)

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

    def test_tracking_response_uses_paginated_ebay_only_path(self):
        options = [{
            'retailer_id': 'ebay', 'name': 'eBay', 'price': 12.5,
            'title': '2024 Bluey Dollarbuck coin',
            'url': 'https://www.ebay.com.au/itm/123456',
        }]
        with mock.patch.object(legacy, '_ebay_live_tracking_options',
                               return_value=(options, False)) as tracker:
            options, complete = buy_options.get_buy_options(
                's1_bluey', '2024 Bluey Dollarbuck coin', tracking=True)
        self.assertFalse(complete)
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]['retailer_id'], 'ebay')
        self.assertEqual(options[0]['url'], 'https://www.ebay.com.au/itm/123456')
        tracker.assert_called_once()

    def test_tracking_discovery_paginates_and_accepts_complete_empty_variants(self):
        retailer = next(r for r in legacy.RETAILERS if r['id'] == 'ebay')
        first = [
            {'price': 5 + i / 100, 'title': '2024 Bluey $1 Dollarbucks Uncirculated Coin',
             'url': f'https://www.ebay.com.au/itm/{100000 + i}', 'subtitle': 'Uncirculated'}
            for i in range(200)
        ]
        last = [{'price': 9.0, 'title': '2024 Bluey $1 Dollarbucks Uncirculated Coin',
                 'url': 'https://www.ebay.com.au/itm/100200', 'subtitle': 'Uncirculated'}]

        def page(query, limit=200, offset=0, sort='price'):
            if query != '2024 $1 Bluey Dollarbucks uncirculated':
                return [], 0, True
            return (first, 201, True) if offset == 0 else (last, 201, True)

        with mock.patch.object(legacy, '_ebay_browse_search_page', side_effect=page):
            options, complete = legacy._ebay_live_tracking_options(
                retailer, '2024 $1 Bluey Dollarbuck coin uncirculated', 's1_bluey')
        self.assertTrue(complete)
        self.assertEqual(len(options), 201)
        self.assertEqual(options[-1]['url'], 'https://www.ebay.com.au/itm/100200')

    def test_tracking_discovery_fails_closed_on_a_failed_page(self):
        retailer = next(r for r in legacy.RETAILERS if r['id'] == 'ebay')
        with mock.patch.object(legacy, '_ebay_browse_search_page', return_value=([], None, False)):
            options, complete = legacy._ebay_live_tracking_options(
                retailer, '2024 $1 Bluey Dollarbuck coin uncirculated', 's1_bluey')
        self.assertEqual(options, [])
        self.assertFalse(complete)

    def test_tracking_discovery_rejects_wrong_quantity_and_mixed_variants(self):
        retailer = next(r for r in legacy.RETAILERS if r['id'] == 'ebay')
        valid = {'price': 12.0, 'title': '2024 Bluey $1 Dollarbucks Uncirculated Coin',
                 'url': 'https://www.ebay.com.au/itm/100001'}
        bundle = {'price': 20.0, 'title': '2 x 2024 Bluey $1 Dollarbucks Coins',
                  'url': 'https://www.ebay.com.au/itm/100002'}
        mixed = {'price': 30.0, 'title': '2024 and 2026 Bluey Bingo mixed coin lot',
                 'url': 'https://www.ebay.com.au/itm/100003'}
        with mock.patch.object(legacy, '_ebay_browse_search_page',
                               return_value=([valid, bundle, mixed], 3, True)):
            options, complete = legacy._ebay_live_tracking_options(
                retailer, '2024 $1 Bluey Dollarbucks coin', 's1_bluey')
        self.assertTrue(complete)
        self.assertEqual([o['url'] for o in options], [valid['url']])

    def test_unknown_coin_is_rejected(self):
        self.assertNotIn('does_not_exist', legacy.COIN_BY_ID)


class TestQueryVariants(unittest.TestCase):
    """Seller-wording variants (from observed eBay AU / CoinXchange titles) widen the
    search; every result must still pass the strict gate for the query that found it."""

    @staticmethod
    def _matches(coin_id, title):
        import re
        queries = [legacy.COIN_BY_ID[coin_id]['search']] + legacy._query_variants(coin_id)
        for query in queries:
            allow = legacy._allow_coloured(query, coin_id)
            if legacy._coinxchange_title_matches(title, legacy._browse_keywords(query), allow):
                return True
        return False

    def test_variants_reference_real_coins_and_are_bounded(self):
        for coin_id, variants in legacy.QUERY_VARIANTS.items():
            self.assertIn(coin_id, legacy.COIN_BY_ID)
            self.assertTrue(variants and all(v.strip() for v in variants))
            self.assertLessEqual(len(variants), 3)

    def test_real_seller_titles_are_found(self):
        for coin_id, title in [
            ('s1_three_coin_set', '2024 Bluey Dollarbucks $1 X 3 coin  Coloured RAM set UNC'),
            ('s1_10_coin_folder_set', '2024 Bluey $1 10x Coin Tube & Folder - Sealed UNC'),
            ('s1_10_coin_folder_opened', '2024 bluey folder and opened coin tube'),
            ('s1_10_coin_folder_opened', 'BLUEY COIN SET OF 10 2024 $1 UNCIRCULATED (opened)'),
            ('s1_impressions_pnc_colour', 'Bluey 2024 Coloured Coin Postal Numismatic Cover (PNC) LIMTED TO 3000 UNITS'),
            ('s1_card_mumdad', "2024 $1 Bluey Dollarbucks- Mum And Dad 'ENVELOPE' Privymark Carded Coin"),
            ('s1_card_grannies', "2024 $1 Bluey Dollarbucks- The Grannies 'ENVELOPE' Privymark Carded Coin"),
            ('s1_card_bingo', "2024 $1 Bluey Dollarbucks- Bingo 'ENVELOPE' Privymark Carded Coin"),
            ('s1_card_blueyfriends', "2024 $1 Bluey Dollarbucks- Bluey And Friends 'ENVELOPE' Privymark Carded Coin"),
            ('s1_card_blueybingofriends', "2024 $1 Bluey Dollarbucks- Bluey, Bingo and Friends 'ENVELOPE' Privymark Coin"),
            ('s1_card_stripes', "2024 $1 Bluey Dollarbucks- Uncle Stripe, Aunty Trixie 'ENVELOPE' Privymark Coin"),
            ('s2_xmas_unc', '2025 Australia $1 One Dollar Bluey Coloured Christmas Uncirculated Coin'),
            ('s2_xmas_unc', 'Bluey Christmas 2025 Dollar Buck $1 One Coloured Coin Australia Blue'),
            ('s2_xmas_silv', '2025 $1 Bluey Christmas Coloured Fine Silver Proof Coin'),
            ('s3_proof_ab', '2026 Bluey $2 Coloured AlBr Proof Coin - Limited to 10,500 minted!'),
            ('s3_proof_silv', '2026 Bluey Silver Proof Coin #8429'),
            ('s3_sleepytime_privy', 'Bluey 2026 $2 Coin in Card with Privy Mark - Sleepytime'),
            ('s3_camping_privy', "2026 $2 Bluey Camping 'Privy Mark' Coin in Card"),
            ('s3_pnc_bingo', 'Bluey 2026 - Bingo - Hooray PNC'),
        ]:
            self.assertTrue(self._matches(coin_id, title), (coin_id, title))

    def test_wider_queries_still_reject_other_products(self):
        for coin_id, title in [
            ('s1_card_mumdad', "2024 $1 Bluey Dollarbucks- Bingo 'ENVELOPE' Privymark Carded Coin"),
            ('s2_xmas_unc', '2025 $1 Bluey Christmas Coloured Fine Silver Proof Coin'),
            ('s3_proof_ab', '2026 $2 Bluey Coloured Silver Proof Coin | 12,000 Mintage'),
            ('s3_proof_silv', '2026 Bluey Silver Proof $2 Coin & Bluey Coloured Proof $2 Coin'),
            ('s3_till_bluey', '2x 2026 Bluey $2 Coloured Coins - Bluey and Bingo Till Coins'),
            ('s3_till_bluey', '2026 $2 Bluey Till Coin Bag (25 x $2 coins total)'),
            ('s3_till_bingo', '2026 $2 Bluey Coloured Coins (till coins)'),
        ]:
            self.assertFalse(self._matches(coin_id, title), (coin_id, title))

    def test_quantity_ignores_denomination_but_counts_sets(self):
        self.assertEqual(legacy._coinxchange_quantity('Bluey 2026 $2 Coin in Card'), 1)
        self.assertEqual(legacy._coinxchange_quantity('2024 Bluey $1 10x Coin Tube'), 10)
        self.assertEqual(legacy._coinxchange_quantity('COIN SET OF 10 2024'), 10)
        self.assertEqual(legacy._coinxchange_quantity('$2 Coin & Proof $2 Coin'), 2)

    def test_browse_keywords_keep_set_size(self):
        self.assertEqual(legacy._browse_keywords('2024 Bluey Dollarbucks $1 X 3 coin Coloured set'),
                         '2024 Bluey Dollarbucks $1 X 3 coin Coloured set')
        self.assertEqual(legacy._browse_keywords('2024 $1 Bluey Dollarbuck till coin'),
                         '2024 $1 Bluey Dollarbucks')

    def test_active_lookup_merges_variants_and_dedupes(self):
        retailer = {'id': 'coinxchange_buy', 'name': 'CoinXchange',
                    'search_url': 'https://www.coinxchange.com.au/buy?search={q}'}
        calls = []

        def fake_scrape(term, sold_only=True):
            calls.append(term)
            if 'Bingo Envelope' in term:
                return [{'price': 40.0, 'title': "2024 $1 Bluey Dollarbucks- Bingo 'ENVELOPE' Privymark Carded Coin", 'url': 'u1'}]
            return []

        with mock.patch.object(legacy, '_scrape_coinxchange', side_effect=fake_scrape):
            out = legacy._coinxchange_buy_options(retailer, legacy.COIN_BY_ID['s1_card_bingo']['search'], coin_id='s1_card_bingo')
        self.assertEqual(len(calls), 2)  # catalogue query, then its one variant
        self.assertEqual([o['price'] for o in out], [40.0])
        self.assertFalse(out[0]['link_only'])

    def test_active_lookup_stops_after_enough_matches(self):
        retailer = {'id': 'coinxchange_buy', 'name': 'CoinXchange',
                    'search_url': 'https://www.coinxchange.com.au/buy?search={q}'}
        rows = [{'price': 10.0 + i, 'title': f'2025 $1 Bluey Christmas Coloured Coin {i}', 'url': f'u{i}'} for i in range(10)]
        with mock.patch.object(legacy, '_scrape_coinxchange', return_value=rows) as scrape:
            out = legacy._coinxchange_buy_options(retailer, legacy.COIN_BY_ID['s2_xmas_unc']['search'], coin_id='s2_xmas_unc')
        self.assertEqual(scrape.call_count, 1)
        self.assertEqual(len(out), 10)

    def test_sold_lookup_merges_variants(self):
        coin = {'id': 's1_card_bingo', 'search': 'x', 'ebay_kw': 'x'}
        seen = []

        def fake(term):
            seen.append(term)
            return [{'price': 40.0, 'title': term, 'url': None, 'sold_date': '1 May 2026'}]

        with mock.patch.object(prices, '_scrape_coinxchange', side_effect=fake):
            rows = prices._scrape_coinxchange_all(coin)
        self.assertEqual(len(rows), 2)  # primary 'x' plus the one variant for this coin id
        with mock.patch.object(prices, '_scrape_coinxchange', return_value=None):
            self.assertIsNone(prices._scrape_coinxchange_all(coin))

    def test_impressions_pnc_titles_allow_coloured_proof_wording(self):
        # Sellers write 'Coloured' on Impressions proof PNCs even though the
        # catalogue query omits it. The proof and pnc groups still apply.
        title = 'PRESALE 2026 Bluey The Heelers $2 Coloured Proof PNC Limited Edition /200'
        self.assertTrue(
            legacy._coinxchange_title_matches(title, 'Heelers Proof PNC',
                                              allow_coloured=True))
        self.assertTrue(
            legacy._coinxchange_title_matches(title, 'Heelers Proof PNC coloured'))
        self.assertFalse(
            legacy._coinxchange_title_matches(title, 'Heelers Proof PNC'))

    def test_variants_do_not_admit_silver_variant(self):
        # 'Heelers Proof PNC' must not match the silver proof PNC.
        title = 'Bluey: The Heelers Silver Proof Limited Edition PNC 700 ONLY'
        self.assertFalse(
            legacy._coinxchange_title_matches(title, 'Heelers Proof PNC',
                                              allow_coloured=True))
        self.assertFalse(
            legacy._coinxchange_title_matches(title, 'Bluey Heelers Proof PNC',
                                              allow_coloured=True))

    def test_impressions_boxed_set_quantity(self):
        boxed = 'Bluey 2026 $2 Coin Minisheet Collection Limited-Edition Boxed Set 5 Presale /500'
        self.assertEqual(legacy._coinxchange_quantity(boxed), 5)
        query = 'Bluey minisheet collection boxed set of 5'
        self.assertEqual(legacy._coinxchange_quantity(query), 5)
        self.assertTrue(
            legacy._coinxchange_title_matches(boxed, query, allow_coloured=True))
        self.assertFalse(
            legacy._coinxchange_title_matches(
                boxed, 'Heelers Proof PNC', allow_coloured=True))

    def test_new_impressions_products_have_variants(self):
        for variant in ('Heelers Proof PNC', 'Bluey Heelers Proof PNC'):
            self.assertIn(variant, legacy.QUERY_VARIANTS['76604950'])
        for variant in ('Bluey 2-coin PNC', 'Bluey $1 $2 2 coin PNC'):
            self.assertIn(variant, legacy.QUERY_VARIANTS['76604956'])
        for variant in ('Bluey boxed set of 5 minisheet collection',
                        'Bluey minisheet collection boxed set of 5'):
            self.assertIn(variant, legacy.QUERY_VARIANTS['76604957'])
        for variant in ('Bluey three coin PNC', 'Bluey 3-coin PNC',
                        'Bluey 3 coin PNC'):
            self.assertIn(variant, legacy.QUERY_VARIANTS['76604959'])
        for variant in ('Bingo 2-coin PNC', 'Bingo $1 $2 2 coin PNC'):
            self.assertIn(variant, legacy.QUERY_VARIANTS['76605600'])

    def test_pair_titles_are_bundles_and_rejected(self):
        # 'Pair - ... $2 Coin' is two separate $2 covers, not the $1+$2 2-coin
        # PNC (76605600) even though quantity('pair') == quantity('2-coin').
        title = 'Pair - 2026 Bluey & Bingo PNC $2 Coin Hooray For Real Life'
        self.assertFalse(
            legacy._coinxchange_title_matches(title, 'Bingo 2-coin PNC',
                                              allow_coloured=True))

    def test_year_less_variant_rejects_wrong_year_title(self):
        # Seller variants omit the year ('Bluey 2-coin PNC'); a 2024 title
        # must not land on a 2026 product. Titles without a year still pass.
        wrong = 'Bluey 2024 Limited Edition 2-Coin Postal Numismatic Cover (PNC)'
        right = '2026 Bluey $1 and $2 Limited-Edition 2-Coin Postal Numismatic Cover (PNC)'
        noyear = 'Bluey Limited Edition 2-Coin Postal Numismatic Cover (PNC)'
        self.assertFalse(
            legacy._coinxchange_title_matches(wrong, 'Bluey 2-coin PNC',
                                              allow_coloured=True,
                                              expected_years={'2026'}))
        self.assertTrue(
            legacy._coinxchange_title_matches(right, 'Bluey 2-coin PNC',
                                              allow_coloured=True,
                                              expected_years={'2026'}))
        self.assertTrue(
            legacy._coinxchange_title_matches(noyear, 'Bluey 2-coin PNC',
                                              allow_coloured=True,
                                              expected_years={'2026'}))

    def test_live_options_excludes_wrong_year_for_2026_product(self):
        retailer = {r['id']: r for r in legacy.RETAILERS}['ebay']
        listings = [
            {'price': 199.99, 'postage': 0.0,
             'title': 'Bluey 2024 Limited Edition 2-Coin Postal Numismatic Cover (PNC)',
             'url': 'https://www.ebay.com.au/itm/wrongyear'},
            {'price': 225.0, 'postage': 0.0,
             'title': '2026 Bluey $1 and $2 Limited-Edition 2-Coin Postal Numismatic Cover (PNC)',
             'url': 'https://www.ebay.com.au/itm/rightyear'},
        ]
        keywords = legacy.COIN_BY_ID['76604956']['search']
        with mock.patch.object(legacy, '_ebay_browse_search', return_value=listings):
            options = legacy._ebay_live_options(retailer, keywords, '76604956')
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]['price'], 225.0)
        self.assertTrue(options[0]['url'].startswith('https://www.ebay.com.au/itm/rightyear'))


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


class TestCatalogueFormatGate(unittest.TestCase):
    # Oct 2026: this plain coloured proof at $899 showed under the silver
    # proof coin's Where to Buy via a silver-less seller-wording variant.
    CX_TITLE = 'Royal Australian Mint 2024 Bluey $1 Coloured Proof Coin'

    def _cx_options(self, coin_id, keywords):
        raw = [{'price': 899.0, 'title': self.CX_TITLE,
                'url': 'https://www.coinxchange.com.au/buy/x',
                'currency': 'AUD', 'seller': 's'}]
        retailer = {r['id']: r for r in legacy.RETAILERS}['coinxchange_buy']
        with mock.patch.object(legacy, '_scrape_coinxchange',
                               return_value=[dict(r) for r in raw]):
            return buy_options._scrape(retailer, keywords, coin_id)

    def test_silver_proof_rejects_plain_coloured_ask(self):
        options = self._cx_options('s1_proof_silver',
                                   '2024 $1 Bluey Dollarbucks fine silver coloured proof')
        self.assertEqual(len(options), 1)
        self.assertTrue(options[0]['link_only'])
        self.assertIsNone(options[0]['price'])

    def test_coloured_proof_keeps_the_same_ask(self):
        options = self._cx_options('s1_proof_coloured',
                                   '2024 $1 Bluey Dollarbucks coloured proof coin')
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]['price'], 899.0)
        self.assertEqual(options[0]['price_type'], 'asking')

    def test_required_format_groups(self):
        self.assertEqual(legacy._required_format_groups(
            '2024 $1 Bluey Dollarbucks fine silver coloured proof'),
            [('proof',), ('silver',)])
        self.assertEqual(legacy._required_format_groups(
            '2024 $1 Bluey Dollarbucks coloured proof coin'), [('proof',)])

    def test_variants_preserve_catalogue_format_tokens(self):
        coins = {c['id']: c for c in legacy.COINS}
        for coin_id, variants in legacy.QUERY_VARIANTS.items():
            if coin_id not in coins:
                continue
            for group in legacy._required_format_groups(coins[coin_id]['ebay_kw']):
                for variant in variants:
                    tokens = set(re.findall(r'[a-z0-9]+', variant.lower()))
                    self.assertTrue(set(group) & tokens,
                                    f'{coin_id} variant drops {group}: {variant}')


class TestBargainLandedPrice(unittest.TestCase):
    def test_postage_reads_free_fixed_and_unknown_costs(self):
        self.assertEqual(legacy._ebay_postage({'shippingOptions': [{'shippingCostType': 'FREE'}]}), 0.0)
        self.assertEqual(legacy._ebay_postage({'shippingOptions': [
            {'shippingCostType': 'FIXED', 'shippingCost': {'value': '6.50', 'currency': 'AUD'}}]}), 6.5)
        # Cheapest known option wins; a calculated option with no value is ignored.
        self.assertEqual(legacy._ebay_postage({'shippingOptions': [
            {'shippingCostType': 'CALCULATED'},
            {'shippingCost': {'value': '9.00'}},
            {'shippingCost': {'value': '4.00'}}]}), 4.0)
        # No shipping data means unknown postage, never assumed free.
        self.assertIsNone(legacy._ebay_postage({}))
        self.assertIsNone(legacy._ebay_postage({'shippingOptions': [{'shippingCostType': 'CALCULATED'}]}))

    def test_bargain_needs_known_postage_and_fifteen_percent_below_median(self):
        below = legacy._deal_fields(18.0, 4.0, 27.99)    # landed 22.00, 21.4% below
        self.assertTrue(below['is_bargain'])
        self.assertEqual(below['landed_price'], 22.0)
        self.assertEqual(below['discount_pct'], 21.4)

        near = legacy._deal_fields(20.0, 4.0, 27.99)     # landed 24.00, 14.2% below
        self.assertFalse(near['is_bargain'])

        unknown_post = legacy._deal_fields(10.0, None, 27.99)
        self.assertFalse(unknown_post['is_bargain'])
        self.assertIsNone(unknown_post['landed_price'])
        self.assertIsNone(unknown_post['discount_pct'])

        no_median = legacy._deal_fields(10.0, 0.0, None)
        self.assertFalse(no_median['is_bargain'])
        self.assertIsNone(no_median['discount_pct'])

    def test_market_median_requires_a_real_sample(self):
        # Median is recomputed from delivered totals (sale_price + shipping).
        # Stored median_price is item-only and no longer returned directly.
        _kw = '2027 $1 Bluey Cricket coloured uncirculated coin'
        def _mk(products):
            return {'median_price': 30.0, 'matched_results': len(products), 'products': [
                {'title': _kw, 'sale_price': pr, 'shipping_price': sh} for pr, sh in products
            ]}
        sales = {'coins': {
            's4_cricket_unc': _mk([(28.0, 2.0), (29.0, 2.0), (30.0, 2.0)]),
            's1_bluey': _mk([(28.0, 2.0), (29.0, 1.0)]),
        }}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'sales.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(sales, f)
            with mock.patch.object(legacy, 'MANUAL_EBAY_SALES_FILE', path):
                with mock.patch.object(legacy, '_cache', {}):
                    with mock.patch.object(legacy, 'CACHE_FILE', '/tmp/nonexistent-cache.json'):
                        self.assertEqual(legacy._market_median('s4_cricket_unc'), 31.0)
                        self.assertIsNone(legacy._market_median('s1_bluey'))
                        self.assertIsNone(legacy._market_median('missing'))

    def test_live_offer_carries_landed_price_and_bargain_flag(self):
        retailer = {r['id']: r for r in legacy.RETAILERS}['ebay']
        listings = [
            {'price': 18.0, 'postage': 4.0, 'title': '2027 Bluey Cricket $1 Coloured Uncirculated Coin',
             'url': 'https://www.ebay.com.au/itm/1'},
            {'price': 30.0, 'postage': 4.0, 'title': '2027 Bluey Cricket $1 Coloured Uncirculated Coin',
             'url': 'https://www.ebay.com.au/itm/2'},
        ]
        keywords = legacy.COIN_BY_ID['s4_cricket_unc']['search']
        with mock.patch.object(legacy, '_market_median', return_value=27.99):
            with mock.patch.object(legacy, '_ebay_browse_search', return_value=listings):
                options = legacy._ebay_live_options(retailer, keywords, 's4_cricket_unc')
        by_price = {o['price']: o for o in options}
        self.assertTrue(by_price[18.0]['is_bargain'])
        self.assertEqual(by_price[18.0]['landed_price'], 22.0)
        self.assertFalse(by_price[30.0]['is_bargain'])
        self.assertEqual(by_price[30.0]['landed_price'], 34.0)
        self.assertEqual(by_price[18.0]['price_type'], 'asking')
    def test_market_median_excludes_bundles_and_lots_for_s1_bluey(self):
        # Raw s1_bluey sample in ebay_cache.json has 24 products with mean ~$44.67
        # and median ~$12.95 because it contains 10-coin sets ($64-$130), rolls ($110),
        # and bags of 20. Excluding those bundles leaves genuine single-coin sales.
        # With the 2026-11-24 verified ledger batch the file holds 25 s1_bluey rows;
        # the surviving delivered sample is 5 singles ($8.45, $9.50, $9.99,
        # $8.90+$1.50 postage, $12.00) with median $9.99. Bundles stay excluded
        # by the $60 window and title matcher; the median moved down on a larger
        # genuine sample, not up on bundle inflation.
        med = legacy._market_median('s1_bluey')
        self.assertIsNotNone(med)
        self.assertEqual(med, 9.99)
        self.assertLess(med, 12.95)

    def test_bargain_detection_rejects_false_bargain_from_bundle_skew(self):
        # With the unpruned median ($12.95), an ask of $10.00 (landed $10.00)
        # would be falsely flagged as a bargain (10.00 <= 12.95 * 0.85 = 11.0075).
        # Against the clean delivered median ($9.99), $10.00 is correctly rejected,
        # while a genuine bargain at $7.50 is recognized.
        clean_median = legacy._market_median('s1_bluey')
        self.assertEqual(clean_median, 9.99)

        false_bargain = legacy._deal_fields(10.0, 0.0, clean_median)
        self.assertFalse(false_bargain['is_bargain'])
        self.assertEqual(false_bargain['landed_price'], 10.0)

        real_bargain = legacy._deal_fields(7.50, 0.0, clean_median)
        self.assertTrue(real_bargain['is_bargain'])
        self.assertEqual(real_bargain['landed_price'], 7.50)
        self.assertGreaterEqual(real_bargain['discount_pct'], 15.0)

    def test_live_options_filters_out_active_bundle_and_lot_listings(self):
        retailer = {r['id']: r for r in legacy.RETAILERS}['ebay']
        listings = [
            {'price': 50.0, 'postage': 0.0, 'title': '2024 $1 Bluey Dollarbuck 10-Coin Set With Folder',
             'url': 'https://www.ebay.com.au/itm/bundle1'},
            {'price': 12.0, 'postage': 0.0, 'title': '2024 $1 Bluey Dollarbuck 2x One Dollar Coins Pair',
             'url': 'https://www.ebay.com.au/itm/bundle2'},
            {'price': 25.0, 'postage': 0.0, 'title': '2024 $1 Bluey Dollarbuck Bulk Lot of 5 Coins',
             'url': 'https://www.ebay.com.au/itm/bundle3'},
            {'price': 9.0, 'postage': 0.0, 'title': '2024 Australia Bluey Uncirculated $1 One Dollar Coin Dollarbuck',
             'url': 'https://www.ebay.com.au/itm/single1'},
        ]
        keywords = legacy.COIN_BY_ID['s1_bluey']['search']
        with mock.patch.object(legacy, '_ebay_browse_search', return_value=listings):
            options = legacy._ebay_live_options(retailer, keywords, 's1_bluey')
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]['price'], 9.0)
        self.assertTrue(options[0]['url'].startswith('https://www.ebay.com.au/itm/single1'))
