"""Regression tests: eBay Browse postage needs a reference delivery postcode.

Confirmed root cause, 2026-11-27: Browse requests without
``X-EBAY-C-ENDUSERCTX`` return a listing with only SELLER_ARRANGED_LOCAL_PICKUP
and no shipping cost, so ``_ebay_postage`` returns None and ``_deal_fields``
leaves postage and landed_price null. With
``contextualLocation=country=AU,zip=3000`` the same listings report CALCULATED
Australia Post postage. Postage is destination dependent: zip 3220 quotes a
different amount, so the reference postcode must be declared, not implied.

No live HTTP calls here; urlopen is replaced.
"""
import importlib.util
import json
import os
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.abspath(__file__))

_SPEC = importlib.util.spec_from_file_location(
    'buy_options_ref', os.path.join(_ROOT, 'api', 'buy-options.py')
)
buy_options = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(buy_options)

import server as legacy  # noqa: E402

ITEM_318_70 = '800955702273'
ITEM_209_99 = '198828044745'
TITLE = '2026 Bluey: Bingo $1 and $2 Limited-Edition 2-Coin PNC 150 ONLY'


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _item(item_id, price, postage=None, title=TITLE):
    """Browse itemSummary; postage None mirrors an unqualified response."""
    item = {
        'title': title,
        'price': {'value': f'{price:.2f}', 'currency': 'AUD'},
        'condition': 'New',
        'itemWebUrl': f'https://www.ebay.com.au/itm/{item_id}',
    }
    if postage is None:
        # eBay without contextualLocation: pick-up only, no cost at all.
        item['deliveryOptions'] = ['SELLER_ARRANGED_LOCAL_PICKUP']
        item['shippingOptions'] = None
    else:
        item['shippingOptions'] = [{
            'shippingCostType': 'CALCULATED',
            'shippingCost': {'value': f'{postage:.2f}', 'currency': 'AUD'},
            'deliveryOptions': ['SHIP_TO_HOME'],
        }]
    return item


def _fetch(item, capture=None):
    """Run one Browse page against a mocked HTTP response; return (items, total, ok)."""
    payload = {'total': 1, 'itemSummaries': [item]}

    def fake_urlopen(req, timeout=None):
        if capture is not None:
            capture.append(req)
        return _FakeResponse(payload)

    with mock.patch.object(legacy, 'EBAY_CLIENT_ID', 'test-client-id'), \
            mock.patch.object(legacy, 'EBAY_CLIENT_SECRET', 'test-client-secret'), \
            mock.patch.object(legacy, '_get_ebay_token', return_value='test-token'), \
            mock.patch.object(legacy.urllib.request, 'urlopen', side_effect=fake_urlopen):
        return legacy._ebay_browse_search_page('2026 Bingo 2 coin PNC', limit=5)


def _header(req, name):
    """Case-insensitive request header lookup (urllib normalises casing)."""
    return {k.lower(): v for k, v in req.header_items()}.get(name.lower())


class TestBrowseReferenceHeader(unittest.TestCase):
    def test_browse_request_declares_reference_postcode(self):
        sent = []
        _fetch(_item(ITEM_318_70, 318.70, postage=6.63), capture=sent)
        self.assertEqual(len(sent), 1)
        self.assertEqual(_header(sent[0], 'X-EBAY-C-ENDUSERCTX'),
                         'contextualLocation=country%3DAU%2Czip%3D3000')

    def test_reference_postcode_is_configurable(self):
        with mock.patch.dict(os.environ, {'EBAY_REFERENCE_POSTCODE': '3220'}):
            sent = []
            _fetch(_item(ITEM_318_70, 318.70, postage=8.26), capture=sent)
            self.assertEqual(_header(sent[0], 'X-EBAY-C-ENDUSERCTX'),
                             'contextualLocation=country%3DAU%2Czip%3D3220')
            self.assertEqual(buy_options.postage_reference()['postcode'], '3220')

    def test_invalid_override_falls_back_to_default(self):
        with mock.patch.dict(os.environ, {'EBAY_REFERENCE_POSTCODE': 'not-a-postcode'}):
            self.assertEqual(legacy._ebay_reference_postcode(), '3000')


class TestPostageAndLanded(unittest.TestCase):
    # Expected values from the read-only trace against eBay Browse API.
    EXPECTED = {
        ITEM_318_70: (318.70, 6.63, 325.33),
        ITEM_209_99: (209.99, 6.63, 216.62),
    }

    def test_unqualified_response_leaves_postage_and_landed_null(self):
        items, total, ok = _fetch(_item(ITEM_318_70, 318.70, postage=None))
        self.assertTrue(ok)
        self.assertIsNone(items[0]['postage'])
        fields = legacy._deal_fields(items[0]['price'], items[0]['postage'], None)
        self.assertIsNone(fields['landed_price'])
        self.assertFalse(fields['is_bargain'])

    def test_qualified_response_returns_postage_and_landed(self):
        for item_id, (price, postage, landed) in self.EXPECTED.items():
            with self.subTest(item=item_id):
                items, total, ok = _fetch(_item(item_id, price, postage=postage))
                self.assertTrue(ok)
                self.assertEqual(items[0]['price'], price)
                self.assertEqual(items[0]['postage'], postage)
                fields = legacy._deal_fields(items[0]['price'], items[0]['postage'], None)
                self.assertEqual(fields['landed_price'], landed)

    def test_free_postage_is_zero_not_unknown(self):
        item = _item(ITEM_318_70, 318.70, postage=None)
        item['shippingOptions'] = [{'shippingCostType': 'FREE'}]
        items, _, ok = _fetch(item)
        self.assertTrue(ok)
        self.assertEqual(items[0]['postage'], 0.0)


class TestTrackingAndProjection(unittest.TestCase):
    def test_tracking_options_carry_postage_for_the_projection(self):
        retailer = next(r for r in legacy.RETAILERS if r['id'] == 'ebay')
        page = [{'price': 318.70, 'postage': 6.63, 'title': TITLE,
                 'url': f'https://www.ebay.com.au/itm/{ITEM_318_70}',
                 'subtitle': 'New'}]

        def fake_page(query, limit=200, offset=0, sort='price'):
            return page, 1, True

        with mock.patch.object(legacy, '_ebay_browse_search_page', side_effect=fake_page):
            options, complete = legacy._ebay_live_tracking_options(
                retailer, '2026 Bingo 2 coin PNC', '76605600')
        self.assertTrue(complete)
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]['price'], 318.70)
        self.assertEqual(options[0]['postage'], 6.63)

    def test_buy_options_response_declares_reference_postcode(self):
        reference = buy_options.postage_reference()
        self.assertEqual(reference, {'country': 'AU', 'postcode': '3000'})


class TestEmptyResultPage(unittest.TestCase):
    """eBay omits itemSummaries on a zero-match page; that is a valid empty page."""

    def _page(self, payload):
        def fake_urlopen(req, timeout=None):
            return _FakeResponse(payload)

        with mock.patch.object(legacy, 'EBAY_CLIENT_ID', 'test-client-id'), \
                mock.patch.object(legacy, 'EBAY_CLIENT_SECRET', 'test-client-secret'), \
                mock.patch.object(legacy, '_get_ebay_token', return_value='test-token'), \
                mock.patch.object(legacy.urllib.request, 'urlopen', side_effect=fake_urlopen):
            return legacy._ebay_browse_search_page('no matches here', limit=200)

    def test_zero_total_without_item_summaries_is_empty_not_failure(self):
        items, total, ok = self._page({'total': 0, 'limit': 200, 'offset': 0,
                                       'href': 'https://api.ebay.com/buy/browse/v1/item_summary/search'})
        self.assertTrue(ok)
        self.assertEqual(items, [])
        self.assertEqual(total, 0)

    def test_missing_item_summaries_with_results_is_still_a_failure(self):
        items, total, ok = self._page({'total': 5, 'limit': 200, 'offset': 0})
        self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()
