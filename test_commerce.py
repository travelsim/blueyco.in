import importlib.util
import json
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
INDEX = (ROOT / 'index.html').read_text(encoding='utf-8')


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'api' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contact = _load('contact')
checkout = _load('checkout')


class TestLeadCapture(unittest.TestCase):
    def test_valid_payload_is_normalised(self):
        fields, error = contact.validate({
            'name': '  Alex Smith ',
            'email': 'Alex@Example.COM',
            'coin': ' 2026 Rain privy coin ',
            'notes': ' x' * 5000,
        })
        self.assertIsNone(error)
        self.assertEqual(fields['name'], 'Alex Smith')
        self.assertEqual(fields['email'], 'alex@example.com')
        self.assertEqual(fields['coin'], '2026 Rain privy coin')
        self.assertEqual(len(fields['notes']), 2000)

    def test_missing_and_malformed_fields_are_rejected(self):
        for payload in (
            {},
            {'name': 'A', 'email': '', 'coin': 'x'},
            {'name': 'A', 'email': 'not-an-email', 'coin': 'x'},
            {'name': '', 'email': 'a@b.co', 'coin': 'x'},
            {'name': 'A', 'email': 'a@b.co', 'coin': ''},
            'a string',
        ):
            fields, error = contact.validate(payload)
            self.assertIsNone(fields, payload)
            self.assertTrue(error, payload)

    def test_undelivered_lead_is_not_reported_as_received(self):
        original = contact.WEBHOOK_URL
        contact.WEBHOOK_URL = ''
        try:
            delivered, detail = contact.deliver({'name': 'A', 'email': 'a@b.co', 'coin': 'c', 'notes': ''})
        finally:
            contact.WEBHOOK_URL = original
        self.assertFalse(delivered)
        self.assertIn('LEAD_WEBHOOK_URL', detail)

    def test_delivery_failure_is_reported_not_swallowed(self):
        original = contact.WEBHOOK_URL
        contact.WEBHOOK_URL = 'http://127.0.0.1:9/unreachable'
        try:
            delivered, detail = contact.deliver({'name': 'A', 'email': 'a@b.co', 'coin': 'c', 'notes': ''})
        finally:
            contact.WEBHOOK_URL = original
        self.assertFalse(delivered)
        self.assertTrue(detail)

    def test_site_posts_the_form_to_the_lead_endpoint(self):
        self.assertIn("fetch('/api/contact'", INDEX)
        self.assertIn('if (data.delivered)', INDEX)
        # The old behaviour confirmed receipt and discarded the submission.
        self.assertNotIn("We've received your request for a custom frame", INDEX.split('if (data.delivered)')[0])


class TestCheckoutHonesty(unittest.TestCase):
    def test_cart_totals_are_computed_from_priced_items(self):
        items, total, error = checkout.validate({'items': [
            {'name': 'Frame A', 'price': 35},
            {'name': 'Frame B', 'price': 15.5},
        ]})
        self.assertIsNone(error)
        self.assertEqual(total, 50.5)
        self.assertEqual(len(items), 2)

    def test_empty_and_invalid_carts_are_rejected(self):
        for payload in ({}, {'items': []}, {'items': 'x'}, {'items': [{'name': '', 'price': 10}]},
                        {'items': [{'name': 'A', 'price': -5}]}, {'items': [{'name': 'A', 'price': 'abc'}]}):
            items, _, error = checkout.validate(payload)
            self.assertIsNone(items, payload)
            self.assertTrue(error, payload)

    def test_checkout_is_off_unless_a_payment_link_is_configured(self):
        original = checkout.PAYMENT_LINK
        checkout.PAYMENT_LINK = ''
        try:
            fields = checkout.validate({'items': [{'name': 'Frame A', 'price': 35}]})
        finally:
            checkout.PAYMENT_LINK = original
        self.assertIsNotNone(fields[0])

    def test_site_does_not_claim_an_order_was_placed(self):
        self.assertIn("fetch('/api/checkout'", INDEX)
        self.assertNotIn('Your order for $', INDEX)
        self.assertNotIn('In a real deployment this would open Stripe Checkout', INDEX)


class TestMedianPricing(unittest.TestCase):
    def test_reference_price_prefers_median_over_mean(self):
        self.assertIn('function _referencePrice(coin)', INDEX)
        self.assertIn("const feedMedian = parseFloat(ebay.median_price);", INDEX)
        self.assertIn("function _referenceFromEntry(entry)", INDEX)

    def test_estimated_value_and_sold_list_include_coinxchange(self):
        self.assertIn("(cx.products || []).forEach(p => out.push(_normSold(p, 'CoinXchange')))", INDEX)
        self.assertIn("current.some(r => r.source.includes('CoinXchange'))", INDEX)
        self.assertNotIn('Show historical eBay sales', INDEX)
        self.assertIn('function buildTrendChart(coin, records)', INDEX)

    def test_card_and_sort_use_the_reference_price(self):
        self.assertIn('const premium = hasMedian ? calcPremium(median, coin.mintPrice) : null;', INDEX)
        self.assertIn('(_referencePrice(b) || 0) - (_referencePrice(a) || 0)', INDEX)
        self.assertIn('(_referencePrice(a) || Infinity) - (_referencePrice(b) || Infinity)', INDEX)

    def test_median_helper_ignores_missing_prices(self):
        self.assertIn('function _medianOfProducts(ebay)', INDEX)
        self.assertIn('prices.filter(price => Number.isFinite(price) && price > 0)', INDEX)


class TestAffiliateDisclosure(unittest.TestCase):
    def test_footer_discloses_epn_and_non_affiliation(self):
        footer = INDEX.split('<footer id="site-footer">')[1].split('</footer>')[0]
        self.assertIn('eBay Partner Network', footer)
        self.assertIn('not affiliated', footer.lower())


if __name__ == '__main__':
    unittest.main()
