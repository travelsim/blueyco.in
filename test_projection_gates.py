"""Projection-gate regressions: reviewed-sale inclusion, taxonomy exclusion,
uncertain-row exclusion, refresh-to-publication fidelity and failure visibility.

Locks the durable pipeline contract: the public /api/prices snapshot must
include every eligibility-reviewed sale at its exact value, must never let
ordinary (non-colour) rows into privy/finish product medians, must never let
uncertain or unreviewed rows move a valuation, and must signal partial
snapshots instead of serving them silently.
"""
import json
import unittest
from pathlib import Path
from unittest import mock

from api import prices

ROOT = Path(__file__).resolve().parent
# Pin the clock inside the 90-day window of the November 2026 reviewed sales.
NOW = 1795488000  # 25 Nov 2026 00:00 UTC


def load_inputs():
    base_cache = json.loads((ROOT / "ebay_cache.json").read_text(encoding="utf-8"))
    manual = json.loads((ROOT / "retailer_prices.json").read_text(encoding="utf-8"))
    imported = json.loads((ROOT / "manual_ebay_sales.json").read_text(encoding="utf-8"))
    manual_ebay_sales = imported.get("coins", imported)
    return base_cache, manual, manual_ebay_sales


def coin(cid):
    return next(c for c in prices.COINS if c["id"] == cid)


class TestReviewedSaleInclusion(unittest.TestCase):
    def test_pr95_rows_project_with_exact_values(self):
        base_cache, manual, manual_ebay_sales = load_inputs()
        with mock.patch.object(prices.time, "time", return_value=NOW):
            snapshot = prices._cached_snapshot(
                [coin("s2_xmas_unc"), coin("s1_proof_silver"), coin("s3_proof_ab")],
                base_cache, manual, manual_ebay_sales,
            )
        by_listing = {}
        for cid, entry in snapshot.items():
            for p in entry["ebay"].get("products", []):
                if p.get("listing_id"):
                    by_listing[p["listing_id"]] = p
        expected = {
            "batch4-061606748f5c5392fc1b034d": 39.0,
            "batch3-8e71e59e48c4fdf29ffd6365": 1102.7,
            "batch3-8e40435c3c532dfec999d923": 220.0,
        }
        for listing_id, sale_price in expected.items():
            self.assertIn(listing_id, by_listing)
            self.assertEqual(by_listing[listing_id]["sale_price"], sale_price)

class TestTaxonomyExclusion(unittest.TestCase):
    DISPUTED = [
        ("s3_camping", "batch3-687fe0264b0a801cb0ea3647", 8.5),
        ("s3_babyrace", "batch3-6b5fbfcc3eafb120a99adf6a", 8.5),
        ("s3_granny", "batch3-c13cea496f17e4b682f383e9", 8.39),
        ("s3_rain", "batch3-c1ffe1011eb54526a6558b0d", 8.9),
    ]

    def test_non_colour_rows_held_from_privy_products(self):
        base_cache, manual, manual_ebay_sales = load_inputs()
        coins = [coin(cid) for cid, _, _ in self.DISPUTED]
        with mock.patch.object(prices.time, "time", return_value=NOW):
            snapshot = prices._cached_snapshot(coins, base_cache, manual, manual_ebay_sales)
        for cid, listing_id, sale_price in self.DISPUTED:
            ebay = snapshot[cid]["ebay"]
            current_ids = [p.get("listing_id") for p in ebay.get("products", [])]
            self.assertNotIn(listing_id, current_ids,
                             f"{listing_id} must stay out of {cid} current products")
            values = [p["sale_price"] for p in ebay.get("products", [])]
            self.assertNotIn(sale_price, values,
                             f"{sale_price} must not move the {cid} median")

    def test_synthetic_ordinary_row_cannot_enter_privy_median(self):
        privy = coin("s3_babyrace")
        row = {
            "title": "2026 BLUEY BABY RACE $2 Coin. 1x AUSTRALIAN Two Dollar Non-Colour Coin",
            "sale_price": 8.5,
            "currency": "AU",
            "date_sold": "23 Nov 2026",
            "source_type": "user_imported_csv",
            "record_status": "Retained",
            "coin_id": "s3_babyrace",
            "listing_id": "synthetic-ordinary-1",
        }
        with mock.patch.object(prices.time, "time", return_value=NOW):
            filtered = prices._quality_filter_ebay({"products": [row]}, privy, now=NOW)
        self.assertEqual(filtered["products"], [])
        self.assertIsNone(filtered["median_price"])


class TestUncertainRowExclusion(unittest.TestCase):
    def test_no_held_or_uncertain_batch_rows_reach_the_committed_file(self):
        _, _, manual_ebay_sales = load_inputs()
        for cid, entry in manual_ebay_sales.items():
            for p in entry.get("products", []):
                lid = p.get("listing_id") or ""
                if lid.startswith(("batch", "manual-")) and p.get("source_type") in (
                    "user_imported_csv", "user_pasted_search",
                ):
                    self.assertEqual(
                        p.get("record_status"), "Retained",
                        f"{lid} published without review",
                    )
                    self.assertEqual(p.get("coin_id"), cid)

    def test_uncertain_till_rows_absent_from_file_and_live(self):
        _, _, manual_ebay_sales = load_inputs()
        for cid in ("s3_till_bluey", "s3_till_bingo"):
            for p in manual_ebay_sales.get(cid, {}).get("products", []):
                self.assertNotEqual(
                    p.get("sale_price"), 5.43,
                    f"uncertain $5.43 row published under {cid}",
                )
                self.assertNotEqual(p.get("listing_id"), "batch3-77101ea0bf57cd1a25201588")
                self.assertNotEqual(p.get("listing_id"), "batch3-5bbf29c68989f35a5a347a23")


class TestRefreshToPublication(unittest.TestCase):
    def test_every_catalogue_id_served(self):
        base_cache, manual, manual_ebay_sales = load_inputs()
        with mock.patch.object(prices.time, "time", return_value=NOW):
            snapshot = prices._cached_snapshot(
                prices.COINS, base_cache, manual, manual_ebay_sales)
        self.assertEqual(set(snapshot), {c["id"] for c in prices.COINS})
        for cid, entry in snapshot.items():
            for section in ("ebay", "coinxchange", "manual"):
                self.assertIn(section, entry)

    def test_partial_snapshot_is_flagged_not_silent(self):
        coins = [{"id": f"c{i}", "search": "x", "ebay_kw": "x"} for i in range(6)]

        def fetch(coin):
            if coin["id"] == "c5":
                prices.time.sleep(3)
            return {"ebay": None, "coinxchange": None}

        _, complete = prices._build_payload(coins, fetch, deadline=0.5)
        self.assertFalse(complete)


if __name__ == "__main__":
    unittest.main()
