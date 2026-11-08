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
        ebay = [{'retailer_id':'ebay','price':p,'postage':shipping,'link_only':False,'url':'https://example.com'} for p,shipping in [(10,30),(20,0),(5,None)] + [(n,1) for n in range(21,32)]]
        cx = [{'retailer_id':'coinxchange_buy','price':19,'postage':0,'link_only':False,'url':'https://example.com'}]
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
