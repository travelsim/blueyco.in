"""Regression tests for GPT code-review findings.

These tests cover production-risk issues that are cheap to verify locally:
- api/prices.py must include _summarise() because handler() calls it.
- server.py rate limiting must key on the visitor IP from forwarded headers,
  not always self.client_address[0] (Render/Cloudflare proxy IP).
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


if __name__ == "__main__":
    unittest.main()
