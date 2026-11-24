"""API payload must surface verified outlier sales without leaking sellers.

_trim_and_strip_payload keeps outliers/historical_outliers and the full
historical list in the payload (Recent Sales reads them); seller stripping
and internal-field removal are unchanged. Medians stay computed from
outlier-free sales only.
"""
import unittest
from unittest import mock

from api import prices

NOW = 1795488000  # 25 Nov 2026 00:00 UTC
COIN_ID = "s3_rain"


def coin():
    return next(c for c in prices.COINS if c["id"] == COIN_ID)


def row(title, price, date, lid):
    return {"title": title, "sale_price": price, "date_sold": date,
            "listing_id": lid, "coin_id": COIN_ID,
            "source_type": "melbourne_confirmed_ledger",
            "record_status": "AutoApproved", "currency": "AU"}


class TestTrimKeepsOutliers(unittest.TestCase):
    def payload(self):
        hist = [row("Oldie %d" % i, 8.0 + i * 0.1, "2024-01-%02d" % ((i % 28) + 1),
                    "hist-%d" % i) for i in range(30)]
        return {"s3_rain": {"ebay": {
            "products": [row("Current", 9.0, "20 Nov 2026", "cur-1")],
            "historical_products": hist,
            "outliers": [row("Wild", 500.0, "21 Nov 2026", "out-1")],
            "historical_outliers": [row("Old wild", 400.0, "2024-02-01", "hout-1")],
            "manual_import": {"x": 1},
            "import_metadata": {"y": 2},
            "response_url": "https://example.test/x",
            "median_price": 9.0,
        }}}

    def test_outliers_and_full_history_survive_trim(self):
        trimmed = prices._trim_and_strip_payload(self.payload())
        ebay = trimmed["s3_rain"]["ebay"]
        self.assertEqual(len(ebay["products"]), 1)
        self.assertEqual(len(ebay["historical_products"]), 30)
        self.assertEqual([r["listing_id"] for r in ebay["outliers"]], ["out-1"])
        self.assertEqual([r["listing_id"] for r in ebay["historical_outliers"]],
                         ["hout-1"])
        for gone in ("manual_import", "import_metadata", "response_url"):
            self.assertNotIn(gone, ebay)

    def test_trim_stays_seller_free(self):
        payload = self.payload()
        payload["s3_rain"]["ebay"]["outliers"][0]["seller"] = "some-seller"
        trimmed = prices._trim_and_strip_payload(payload)

        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertNotEqual(key, "seller")
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(trimmed)


class TestMedianExcludesOutliers(unittest.TestCase):
    def test_median_ignores_iqr_outlier(self):
        rows = [row("A", 10.0, "20 Nov 2026", "a"),
                row("B", 11.0, "20 Nov 2026", "b"),
                row("C", 12.0, "20 Nov 2026", "c"),
                row("Spike", 1000.0, "20 Nov 2026", "d")]
        with mock.patch.object(prices.time, "time", return_value=NOW):
            filtered = prices._quality_filter_ebay({"products": rows},
                                                   coin(), now=NOW)
        self.assertEqual(filtered["median_price"], 11)
        self.assertEqual([p["listing_id"] for p in filtered["outliers"]], ["d"])


if __name__ == "__main__":
    unittest.main()
