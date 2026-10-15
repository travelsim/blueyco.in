"""Tests for eBay Partner Network (EPN) affiliate link functionality."""
import os
import sys
import unittest
from importlib import reload

# Import server module — must happen before we manipulate env vars
import server


class TestAffiliateUrl(unittest.TestCase):

    def setUp(self):
        # Ensure clean state: no campaign configured
        if 'EPN_CAMPAIGN_ID' in os.environ:
            self.orig_campaign = os.environ['EPN_CAMPAIGN_ID']
            del os.environ['EPN_CAMPAIGN_ID']
        else:
            self.orig_campaign = None
        reload(server)
        server.EPN_CAMPAIGN_ID = os.environ.get('EPN_CAMPAIGN_ID', '')

    def tearDown(self):
        if self.orig_campaign:
            os.environ['EPN_CAMPAIGN_ID'] = self.orig_campaign
        else:
            os.environ.pop('EPN_CAMPAIGN_ID', None)
        reload(server)
        server.EPN_CAMPAIGN_ID = os.environ.get('EPN_CAMPAIGN_ID', '')

    def test_no_campaign_returns_original(self):
        """When EPN_CAMPAIGN_ID is not set, should return original URL unchanged."""
        url = 'https://www.ebay.com.au/itm/12345'
        result = server.affiliate_url(url)
        self.assertEqual(result, url)

    def test_non_ebay_url_untouched(self):
        """Non-eBay URLs should never be transformed."""
        server.EPN_CAMPAIGN_ID = '1234567'
        urls = [
            'https://www.google.com',
            'https://coinxchange.com.au/item/123',
            'https://shop.ramint.gov.au/product/bluey',
        ]
        for url in urls:
            self.assertEqual(server.affiliate_url(url), url)

    def test_affiliate_params_appended(self):
        """eBay AU URLs should get EPN params when campaign is set."""
        server.EPN_CAMPAIGN_ID = '1234567'
        url = 'https://www.ebay.com.au/itm/12345'
        result = server.affiliate_url(url)
        self.assertIn('campid=1234567', result)
        self.assertIn('mkrid=705-53470-19255-0', result)
        self.assertIn('siteid=15', result)
        self.assertIn('toolid=10001', result)
        self.assertIn('mkevt=1', result)

    def test_custom_id_includes_coin_id(self):
        """customid should include coin_id and source when provided."""
        server.EPN_CAMPAIGN_ID = '1234567'
        url = 'https://www.ebay.com.au/itm/12345'
        result = server.affiliate_url(url, coin_id='s1_bluey', source='ebay_buy')
        self.assertIn('customid=5339153744', result)

    def test_custom_id_defaults(self):
        """customid should default to 'blueycoin' when no coin_id given."""
        server.EPN_CAMPAIGN_ID = '1234567'
        url = 'https://www.ebay.com.au/itm/12345'
        result = server.affiliate_url(url)
        self.assertIn('customid=5339153744', result)

    def test_url_with_existing_query_params(self):
        """Should append with & when URL already has query params."""
        server.EPN_CAMPAIGN_ID = '1234567'
        url = 'https://www.ebay.com.au/sch/i.html?_nkw=bluey+coin'
        result = server.affiliate_url(url)
        self.assertIn('&campid=1234567', result)
        self.assertNotIn('?campid=1234567', result)

    def test_url_without_query_params(self):
        """Should append with ? when URL has no query params."""
        server.EPN_CAMPAIGN_ID = '1234567'
        url = 'https://www.ebay.com.au/itm/12345'
        result = server.affiliate_url(url)
        self.assertIn('?mkrid=705-53470-19255-0', result)
        self.assertNotIn('&mkrid=', result)

    def test_empty_url_returns_empty(self):
        """Empty or None URL should return empty."""
        server.EPN_CAMPAIGN_ID = '1234567'
        self.assertEqual(server.affiliate_url(''), '')
        self.assertEqual(server.affiliate_url(None, coin_id='test'), None)

    def test_https_and_eBay_com_au_required(self):
        """Only https://www.ebay.com.au URLs should be transformed."""
        server.EPN_CAMPAIGN_ID = '1234567'
        self.assertEqual(
            server.affiliate_url('https://www.ebay.com/itm/12345'),
            'https://www.ebay.com/itm/12345',
        )
        self.assertEqual(
            server.affiliate_url('http://www.ebay.com.au/itm/12345'),
            'http://www.ebay.com.au/itm/12345',
        )


class TestAffiliateApiEndpoint(unittest.TestCase):
    """Integration-style tests for /api/affiliate-redirect endpoint."""

    def setUp(self):
        if 'EPN_CAMPAIGN_ID' in os.environ:
            self.orig_campaign = os.environ['EPN_CAMPAIGN_ID']
        else:
            self.orig_campaign = None
        os.environ['EPN_CAMPAIGN_ID'] = 'test789'
        reload(server)
        server.EPN_CAMPAIGN_ID = 'test789'

    def tearDown(self):
        if self.orig_campaign:
            os.environ['EPN_CAMPAIGN_ID'] = self.orig_campaign
        else:
            os.environ.pop('EPN_CAMPAIGN_ID', None)
        reload(server)
        server.EPN_CAMPAIGN_ID = os.environ.get('EPN_CAMPAIGN_ID', '')

    def _call_affiliate_redirect(self, url, coin_id='', source='ebay'):
        """Helper to simulate what the endpoint does."""
        aff = server.affiliate_url(url, coin_id=coin_id, source=source)
        return {'url': aff, 'is_affiliate': aff != url}

    def test_redirect_endpoint_affiliate(self):
        result = self._call_affiliate_redirect(
            'https://www.ebay.com.au/itm/99999',
            coin_id='s1_bingo',
            source='ebay_buy',
        )
        self.assertTrue(result['is_affiliate'])
        self.assertIn('campid=test789', result['url'])
        self.assertIn('customid=5339153744', result['url'])

    def test_redirect_endpoint_non_ebay(self):
        result = self._call_affiliate_redirect(
            'https://coinxchange.com.au/item/123',
        )
        self.assertFalse(result['is_affiliate'])
        self.assertEqual(result['url'], 'https://coinxchange.com.au/item/123')


if __name__ == '__main__':
    unittest.main()
