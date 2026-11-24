"""Regression tests for the durable Melbourne-to-publication drift path.

Locks the classifier (published / held / pending-review / old-history) and
the publication-hold enforcement in the serving projection, using fixtures so
no test touches the network or the database.
"""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

from api import prices
from scripts import melbourne_drift as drift

ROOT = Path(__file__).resolve().parent
NOW = 1795488000  # 25 Nov 2026 00:00 UTC

HOLDS_PATH = str(ROOT / "publication_holds.json")
HELD_IDS = [
    "batch3-77101ea0bf57cd1a25201588",
    "batch3-5bbf29c68989f35a5a347a23",
]


def row(prod, title, price, date, lid, source="user_imported_csv"):
    return {"product_id": prod, "title": title, "price_aud": price,
            "date_sold": date, "listing_id": lid, "source": source}


def taxonomy_hold(title, prod):
    coin = next((c for c in prices.COINS if c["id"] == prod), None)
    if coin is None:
        return False
    return prices._reviewed_format_mismatch(title, coin)


class TestDriftClassifier(unittest.TestCase):
    def test_published_row_counts_as_published(self):
        index = {("s3_rain", "2026 bluey raining 2 coin", 8.9, "2026-11-23")}
        report = drift.classify(
            [row("s3_rain", "2026 BLUEY RAINING $2 Coin", 8.9, "23 Nov 2026",
                 "batch3-c1ffe1011eb54526a6558b0d")],
            index, {"s3_rain": "2026-11-23"}, {})
        self.assertEqual(report["published"], 1)
        self.assertEqual(report["pending_review"], [])

    def test_hold_listed_row_is_held_not_pending(self):
        report = drift.classify(
            [row("s3_till_bluey", "Bluey For Real Life 2026 Two Dollar Bucks",
                 5.43, "23 Nov 2026", HELD_IDS[1])],
            set(), {"s3_till_bluey": "2026-10-17"},
            {HELD_IDS[1]: "uncertain attribution"})
        self.assertEqual(len(report["held"]), 1)
        self.assertEqual(report["held"][0]["reason"], "publication-hold")
        self.assertEqual(report["pending_review"], [])

    def test_taxonomy_mismatch_is_held_not_pending(self):
        report = drift.classify(
            [row("s3_rain", "2026 BLUEY RAINING $2 Coin Non-Colour Coin", 8.9,
                 "23 Nov 2026", "batch3-c1ffe1011eb54526a6558b0d")],
            set(), {"s3_rain": "2026-09-14"}, {},
            taxonomy_hold=taxonomy_hold)
        self.assertEqual(len(report["held"]), 1)
        self.assertEqual(report["held"][0]["reason"], "taxonomy-gate")

    def test_newer_unmapped_row_is_pending_review(self):
        report = drift.classify(
            [row("s1_pnc_stripes", "2024 Bluey Postal Numismatic Covers PNC",
                 39.95, "2 Oct 2026", "manual-e8b79837323098d0")],
            set(), {"s1_pnc_stripes": "2026-07-17"}, {},
            strict_match=lambda r, p: False)
        self.assertEqual(len(report["pending_review"]), 1)
        item = report["pending_review"][0]
        self.assertEqual(item["published_newest"], "2026-07-17")
        self.assertFalse(item["would_project_unmapped"])

    def test_older_row_is_old_history(self):
        report = drift.classify(
            [row("s3_folder", "2026 Bluey $2 Folder", 38.0, "18 May 2026",
                 "397934805570")],
            set(), {"s3_folder": "2026-11-05"}, {})
        self.assertEqual(report["old_history"], 1)
        self.assertEqual(report["pending_review"], [])


class TestPublicationHoldsFile(unittest.TestCase):
    def test_holds_file_lists_both_uncertain_till_rows(self):
        holds = drift.load_holds(HOLDS_PATH)
        for lid in HELD_IDS:
            self.assertIn(lid, holds)

    def test_held_rows_excluded_from_projection_even_when_retained(self):
        till = next(c for c in prices.COINS if c["id"] == "s3_till_bluey")
        held_row = {
            "title": "Bluey For Real Life 2026 Two Dollar Bucks Coin Bingo",
            "sale_price": 5.43,
            "currency": "AU",
            "date_sold": "23 Nov 2026",
            "source_type": "user_imported_csv",
            "record_status": "Retained",
            "coin_id": "s3_till_bluey",
            "listing_id": HELD_IDS[1],
        }
        with mock.patch.object(prices.time, "time", return_value=NOW):
            filtered = prices._quality_filter_ebay({"products": [held_row]},
                                                   till, now=NOW)
        self.assertEqual(filtered["products"], [])
        self.assertIsNone(filtered["median_price"])

    def test_hold_loader_tolerates_missing_file(self):
        self.assertEqual(drift.load_holds(str(ROOT / "no-such.json")), {})


class TestProjectionHeldVisibility(unittest.TestCase):
    def test_committed_but_excluded_rows_are_listed(self):
        held = drift.projection_held_rows(str(ROOT))
        by_id = {h.get("listing_id"): h for h in held}
        for lid in ("batch3-687fe0264b0a801cb0ea3647",
                    "batch3-6b5fbfcc3eafb120a99adf6a",
                    "batch3-c13cea496f17e4b682f383e9",
                    "batch3-c1ffe1011eb54526a6558b0d"):
            self.assertIn(lid, by_id)
            self.assertEqual(by_id[lid]["reason"], "taxonomy-gate")


if __name__ == "__main__":
    unittest.main()
