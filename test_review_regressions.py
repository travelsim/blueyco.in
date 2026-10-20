"""Regression tests for GPT code-review findings.

These tests cover production-risk issues that are cheap to verify locally:
- api/prices.py must include _summarise() because handler() calls it.
- server.py rate limiting must key on the visitor IP from forwarded headers,
  not always self.client_address[0] (Render/Cloudflare proxy IP).
- api/prices.py must reject bundle/folder/set cross-contamination and filter
  price outliers so single-coin estimates remain accurate.
"""
import importlib.util
from pathlib import Path
import unittest

import server

ROOT = Path(__file__).resolve().parent


def load_api_prices_module():
    spec = importlib.util.spec_from_file_location("api_prices", ROOT / "api" / "prices.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestVercelPriceFunctionRegressions(unittest.TestCase):
    def test_api_prices_has_summarise_helper_used_by_handler(self):
        prices = load_api_prices_module()
        self.assertTrue(hasattr(prices, "_summarise"))

        summary = prices._summarise([
            {"price": 12.0, "title": "low", "url": "https://example.test/low"},
            {"price": 18.0, "title": "high", "url": "https://example.test/high"},
        ])

        self.assertEqual(summary["average_price"], 15.0)
        self.assertEqual(summary["min_price"], 12.0)
        self.assertEqual(summary["max_price"], 18.0)
        self.assertEqual(summary["total_results"], 2)
        self.assertEqual(len(summary["products"]), 2)

    def test_api_prices_summarise_empty_list_returns_none(self):
        prices = load_api_prices_module()
        self.assertIsNone(prices._summarise([]))


class TestRateLimitVisitorIpRegressions(unittest.TestCase):
    def test_client_ip_prefers_cloudflare_connecting_ip(self):
        headers = {"CF-Connecting-IP": "203.0.113.10", "X-Forwarded-For": "198.51.100.1"}
        self.assertEqual(server._client_ip(headers, ("10.0.0.5", 12345)), "203.0.113.10")

    def test_client_ip_uses_first_x_forwarded_for_ip(self):
        headers = {"X-Forwarded-For": "198.51.100.7, 10.0.0.5"}
        self.assertEqual(server._client_ip(headers, ("10.0.0.5", 12345)), "198.51.100.7")

    def test_client_ip_falls_back_to_socket_address(self):
        self.assertEqual(server._client_ip({}, ("10.0.0.5", 12345)), "10.0.0.5")


class TestPriceOutlierAndBundleRegressions(unittest.TestCase):
    def test_product_matches_coin_rejects_folder_set_for_single_till_coin(self):
        prices = load_api_prices_module()
        coin = next(c for c in prices.COINS if c["id"] == "s3_till_bluey")

        # Multi-coin folder tube set listing title observed on CoinXchange
        mismatched_cx_title = "2026 Bluey $2 Folder Tube Set: Coloured Sleeptime + Coloured Till Coins"
        product = {
            "title": mismatched_cx_title,
            "sale_price": 175.0,
            "date_sold": "25 Jul 2026",
            "currency": "AUD",
        }
        self.assertFalse(prices._product_matches_coin(product, coin, now=1792000000))

        # Genuine single till coin listing title observed on eBay AU
        genuine_title = "2026 $2 BLUEY COLOURED TILL COIN ( Bluey ) UNCIRCULATED"
        product_ok = {
            "title": genuine_title,
            "sale_price": 7.99,
            "date_sold": "24 Aug 2026",
            "currency": "AUD",
        }
        self.assertTrue(prices._product_matches_coin(product_ok, coin, now=1792000000))

    def test_filter_price_outliers_prunes_domain_and_statistical_outliers(self):
        prices = load_api_prices_module()
        till_coin = next(c for c in prices.COINS if c["id"] == "s3_till_bluey")

        # Mix of genuine till sales and high set outliers
        products = [
            {"sale_price": 4.99, "title": "coin 1"},
            {"sale_price": 7.99, "title": "coin 2"},
            {"sale_price": 170.0, "title": "outlier set 1"},
            {"sale_price": 175.0, "title": "outlier set 2"},
        ]
        valid, outliers = prices._filter_price_outliers(products, till_coin)
        self.assertEqual([p["sale_price"] for p in valid], [4.99, 7.99])
        self.assertEqual(len(outliers), 2)

        # Abnormally low anomaly on carded coin
        rain_coin = next(c for c in prices.COINS if c["id"] == "s3_rain_privy")
        low_product = [{"sale_price": 2.0, "title": "empty card"}]
        valid_low, outliers_low = prices._filter_price_outliers(low_product, rain_coin)
        self.assertEqual(valid_low, [])
        self.assertEqual(len(outliers_low), 1)

    def test_payload_for_s3_till_bluey_excludes_folder_set_outliers(self):
        prices = load_api_prices_module()
        coin = next(c for c in prices.COINS if c["id"] == "s3_till_bluey")

        payload, _ = prices._build_payload(
            [coin],
            fetch_coin=lambda c: {"ebay": None, "coinxchange": None},
            deadline=1,
        )
        bluey = payload["s3_till_bluey"]
        self.assertEqual(bluey["ebay"]["median_price"], 6.79)
        self.assertEqual(bluey["coinxchange"]["matched_results"], 0)
        self.assertEqual(bluey["coinxchange"]["products"], [])


if __name__ == "__main__":
    unittest.main()
