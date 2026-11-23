import importlib.util
import pathlib
import unittest
from unittest.mock import patch
import server

spec = importlib.util.spec_from_file_location('buy_options_top_ten', pathlib.Path(__file__).parent / 'api' / 'buy-options.py')
buy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(buy)

class DeliveredPriceTests(unittest.TestCase):
    def test_delivered_price_ranking_across_sellers_and_unknown_postage(self):
        buy._cache.clear()
        retailers = [{'id':'ebay','name':'eBay'}, {'id':'coinxchange_buy','name':'CoinXchange'}]
        ebay = [{'retailer_id':'ebay','price':p,'postage':shipping,'link_only':False,
                 'url':f'https://www.ebay.com.au/itm/{900000 + p}?item={p}'} for p,shipping in [(10,30),(20,0),(5,None)] + [(n,1) for n in range(21,32)]]
        cx = [{'retailer_id':'coinxchange_buy','price':19,'postage':0,'link_only':False,'url':'https://example.com/cx/19'}]
        with patch.object(server, 'RETAILERS', retailers), patch.object(buy, '_manual', return_value={}), patch.object(buy, '_scrape', side_effect=lambda r, k, c: ebay if r['id']=='ebay' else cx):
            options, _ = buy.get_buy_options('test', 'test')
        self.assertEqual(len(options), 10)
        self.assertEqual([(x['price'],x['postage']) for x in options[:3]],[(19,0),(20,0),(21,1)])
        self.assertNotIn((5,None),[(x['price'],x['postage']) for x in options])

    def test_postage_not_assumed_free(self):
        self.assertLess(server._buy_total_sort_key({'price':20,'postage':0}), server._buy_total_sort_key({'price':1,'postage':None}))
        rows=server._cx_parse_active(['Example Bluey','AU $10.00','Buy It Now','Seller'], [None]*4)
        self.assertIsNone(rows[0]['postage'])
        rows=server._cx_parse_active(['Example Bluey','AU $10.00','Buy It Now','Free postage','Seller'], [None]*5)
        self.assertEqual(rows[0]['postage'],0)


class DuplicateListingTests(unittest.TestCase):
    def test_listing_identity_ignores_the_search_variant(self):
        a = {'retailer_id': 'ebay', 'url': 'https://www.ebay.com.au/itm/135350914448?_skw=alpha'}
        b = {'retailer_id': 'ebay', 'url': 'https://www.ebay.com.au/itm/135350914448?_skw=beta'}
        self.assertEqual(server._listing_key(a), server._listing_key(b))

    def test_distinct_items_keep_distinct_identities(self):
        a = {'retailer_id': 'ebay', 'url': 'https://www.ebay.com.au/itm/135350914448?_skw=alpha'}
        b = {'retailer_id': 'ebay', 'url': 'https://www.ebay.com.au/itm/940067484749?_skw=alpha'}
        self.assertNotEqual(server._listing_key(a), server._listing_key(b))

    def test_duplicate_rows_collapse_and_keep_order(self):
        rows = [
            {'retailer_id': 'ebay', 'url': 'https://www.ebay.com.au/itm/1?_skw=a', 'price': 20},
            {'retailer_id': 'ebay', 'url': 'https://www.ebay.com.au/itm/1?_skw=b', 'price': 20},
            {'retailer_id': 'ebay', 'url': 'https://www.ebay.com.au/itm/2?_skw=a', 'price': 25},
        ]
        self.assertEqual([r['price'] for r in server._dedupe_listings(rows)], [20, 25])

    def test_same_item_found_by_three_variants_fills_one_slot(self):
        buy._cache.clear()
        retailers = [{'id': 'ebay', 'name': 'eBay'}]
        item = {'retailer_id': 'ebay', 'price': 24.95, 'postage': 5.0, 'link_only': False,
                'url': 'https://www.ebay.com.au/itm/135350914448?_skw=v1'}
        same = dict(item, url='https://www.ebay.com.au/itm/135350914448?_skw=v2')
        other = {'retailer_id': 'ebay', 'price': 29.95, 'postage': 0, 'link_only': False,
                 'url': 'https://www.ebay.com.au/itm/940067484749?_skw=v1'}
        with patch.object(server, 'RETAILERS', retailers), patch.object(buy, '_manual', return_value={}), \
                patch.object(buy, '_scrape', return_value=[item, same, other]):
            options, _ = buy.get_buy_options('test', 'test')
        self.assertEqual([o['price'] for o in options], [24.95, 29.95])


class ImpressionsStampCoverExclusionTests(unittest.TestCase):
    def test_stamp_and_pin_covers_are_not_listed_as_the_coin_pnc(self):
        retailer = {'id': 'ebay', 'name': 'eBay AU', 'type': 'ebay_live', 'search_url': 'https://example.com/?q={q}'}
        listings = [
            {'title': '2026 Australia PNC Bluey Sleepytime Stamp & Pin Cover (Individually Numbered)', 'price': 69.25, 'postage': 8.0, 'url': 'https://www.ebay.com.au/itm/111000000001'},
            {'title': 'Bluey: Sleepytime Limited-Edition PNC Only 3.5k Made', 'price': 149.0, 'postage': 9.0, 'url': 'https://www.ebay.com.au/itm/111000000002'},
        ]
        with patch.object(server, '_ebay_browse_search', return_value=listings), \
                patch.object(server, '_market_median', return_value=None):
            out = server._ebay_live_options(retailer, '2026 Bluey Sleepytime PNC', coin_id='76604949')
        # Affiliate tracking parameters are appended to the item URL; compare the item itself.
        self.assertEqual([o['url'].split('?')[0] for o in out], ['https://www.ebay.com.au/itm/111000000002'])
