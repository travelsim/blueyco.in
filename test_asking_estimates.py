import importlib.util
import os
import unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location(
    "refresh_asking_estimates",
    os.path.join(ROOT, "scripts", "refresh_asking_estimates.py"))
asking = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(asking)

NOW = datetime(2026, 11, 29, 1, 0, tzinfo=timezone.utc)


class TestAskingEstimates(unittest.TestCase):
    def test_single_offer_uses_the_lowest_price(self):
        out = asking.summarise([("s1_bluey", 12.5, 3.0)], now=NOW)
        row = out["products"]["s1_bluey"]
        self.assertEqual(row["count"], 1)
        self.assertEqual(row["lowest"], 12.5)
        self.assertEqual(row["value"], 12.5)

    def test_three_or_more_offers_use_the_median(self):
        rows = [("s1_bluey", p, 0) for p in (40.0, 10.0, 20.0)]
        row = asking.summarise(rows, now=NOW)["products"]["s1_bluey"]
        self.assertEqual(row["count"], 3)
        self.assertEqual(row["lowest"], 10.0)
        self.assertEqual(row["median"], 20.0)
        self.assertEqual(row["value"], 20.0)

    def test_delivered_lowest_includes_postage_and_flags_unknown(self):
        rows = [("x", 30.0, 25.0), ("x", 40.0, None), ("x", 45.0, 5.0)]
        row = asking.summarise(rows, now=NOW)["products"]["x"]
        # 40 + unknown postage is treated as 40 for the ranking, never free.
        self.assertEqual(row["delivered_lowest"], 40.0)
        self.assertEqual(row["unknown_postage"], 1)

    def test_invalid_and_zero_prices_are_skipped(self):
        rows = [("x", 0, 0), ("x", None, 0), ("", 10.0, 0), ("x", 15.0, 0)]
        out = asking.summarise(rows, now=NOW)
        self.assertEqual(list(out["products"]), ["x"])
        self.assertEqual(out["products"]["x"]["count"], 1)
        self.assertEqual(out["products"]["x"]["value"], 15.0)

    def test_payload_shape_is_stable(self):
        out = asking.summarise([("x", 10.0, 2.0)], now=NOW)
        self.assertEqual(out["source"], "active_offers")
        self.assertEqual(out["generatedAt"], "2026-11-29T01:00:00+00:00")
        self.assertEqual(
            set(out["products"]["x"]),
            {"count", "lowest", "median", "value", "delivered_lowest",
             "unknown_postage"})


if __name__ == "__main__":
    unittest.main()
