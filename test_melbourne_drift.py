"""Regression tests for the durable Melbourne-to-publication drift path.

Locks the classifier (published / held / pending-review / old-history) and
the publication-hold enforcement in the serving projection, using fixtures so
no test touches the network or the database.
"""
import importlib.util
import json
from tempfile import TemporaryDirectory
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
        self.assertNotIn("would_project_unmapped", item)
        self.assertEqual(len(report["approved_awaiting"]), 0)

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
        with TemporaryDirectory() as folder:
            publication = {"coins": {"s3_camping": {"products": [
                {"listing_id": "non-colour", "title": "Bluey $2 Camping non-colour"},
                {"listing_id": "privy", "title": "Bluey $2 Camping Privy Mark"},
            ]}}}
            (Path(folder) / "manual_ebay_sales.json").write_text(
                json.dumps(publication), encoding="utf-8")
            held = drift.projection_held_rows(folder)
        self.assertEqual([(row["listing_id"], row["reason"]) for row in held],
                         [("non-colour", "taxonomy-gate")])


class TestJsonFetchParsing(unittest.TestCase):
    def test_pipe_and_newline_titles_parse_exactly(self):
        blob = (
            '{"product_id": "s3_rain", "title": "Rain | Pour | Coin",'
            ' "price_aud": 8.9, "date_sold": "2026-11-23",'
            ' "listing_id": "a|b", "source": "s"}\n'
            '{"product_id": "s3_rain", "title": "Line1\\nLine2",'
            ' "price_aud": 9.9, "date_sold": "2026-11-24",'
            ' "listing_id": "c", "source": "s"}\n'
            'not json\n'
        )
        rows, bad = drift.parse_json_lines(blob)
        self.assertEqual(len(rows), 2)
        self.assertEqual(bad, 1)
        self.assertEqual(rows[0]["title"], "Rain | Pour | Coin")
        self.assertEqual(rows[0]["listing_id"], "a|b")
        self.assertIn("\n", rows[1]["title"])


class TestClassifyAccounting(unittest.TestCase):
    def test_every_input_row_is_counted(self):
        rows = [
            row("s3_rain", "2026 BLUEY RAINING $2 Coin", 8.9, "23 Nov 2026", "lid1"),
            row("s3_rain", "No price here", None, "23 Nov 2026", "lid2"),
            row("s3_rain", "Oldie", 5.0, "1 Jan 2020", "lid3"),
            row("newprod", "Brand new thing", 9.0, "24 Nov 2026", "lid4"),
            row("newprod", "Mappable thing", 10.0, "24 Nov 2026", "lid5"),
        ]
        index = {("s3_rain", "2026 bluey raining 2 coin", 8.9, "2026-11-23")}
        report = drift.classify(
            rows, index, {"s3_rain": "2026-11-23", "newprod": "2026-01-01"},
            {}, strict_match=lambda r, p: r["listing_id"] == "lid5")
        total = (report["published"] + len(report["held"])
                 + len(report["pending_review"]) + len(report["approved_awaiting"])
                 + report["old_history"] + len(report["incomplete"]))
        self.assertEqual(report["total_input"], 5)
        self.assertEqual(total, 5)
        self.assertEqual(report["published"], 1)
        self.assertEqual(len(report["incomplete"]), 1)
        self.assertEqual(report["old_history"], 1)
        self.assertEqual(len(report["approved_awaiting"]), 1)
        self.assertEqual(report["approved_awaiting"][0]["row"]["listing_id"], "lid5")
        self.assertEqual(len(report["pending_review"]), 1)
        self.assertEqual(report["pending_review"][0]["row"]["listing_id"], "lid4")


class TestReverseCheck(unittest.TestCase):
    def test_unmatched_and_unverifiable(self):
        committed = [
            {"coin_id": "s3_rain", "row": {"listing_id": "in-mel", "title": "t"}},
            {"coin_id": "s3_rain", "row": {"listing_id": "gone", "title": "t"}},
            {"coin_id": "s3_rain", "row": {"title": "no id"}},
        ]
        out = drift.reverse_check(committed, {"in-mel"})
        self.assertEqual(len(out["unmatched"]), 1)
        self.assertEqual(out["unmatched"][0]["row"]["listing_id"], "gone")
        self.assertEqual(len(out["unverifiable"]), 1)


class TestCollectionGaps(unittest.TestCase):
    def test_zero_sale_and_overdue(self):
        prods = [
            {"product_id": "a", "name": "A", "confirmed_count": 0,
             "has_listings": False, "max_last_seen": None},
            {"product_id": "b", "name": "B", "confirmed_count": 3,
             "has_listings": True, "max_last_seen": "2020-01-01T00:00:00+00:00"},
            {"product_id": "c", "name": "C", "confirmed_count": 3,
             "has_listings": True,
             "max_last_seen": drift.datetime.now().isoformat()},
        ]
        out = drift.collection_gaps(prods)
        self.assertEqual([p["product_id"] for p in out["zero_sale"]], ["a"])
        self.assertEqual([p["product_id"] for p in out["overdue"]], ["b"])


if __name__ == "__main__":
    unittest.main()
