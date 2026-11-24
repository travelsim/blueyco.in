"""Regression tests for the seller-free publication generator.

Fixtures only: no network, no database. Live fetch functions are not
exercised here; generate()/carry_over_committed()/verify logic is.
"""
import json
import unittest
from unittest import mock

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import publish_sold as pub


def mrow(pid, title, price, date, lid, source="manual_upload", url=None):
    return {"product_id": pid, "title": title, "price_aud": price,
            "date_sold": date, "listing_id": lid, "source": source,
            "source_url": url, "currency": "AUD", "condition": None,
            "buying_format": None}


def idx(*keys):
    return set(keys)


def newest(pid, date):
    return {pid: date}


class TestManifestCompleteness(unittest.TestCase):
    def test_every_input_row_accounted(self):
        rows = [
            mrow("p1", "Alpha Coin", 10.0, "2026-11-20", "a"),
            mrow("p1", "Beta Coin", 12.0, "2026-11-21", "b"),
            mrow("p1", "Held Thing", 5.43, "2026-11-22", "held1"),
            mrow("p1", "Future?", None, "2026-11-22", "c"),
            mrow("p1", "Mystery", 9.0, "2026-11-22", "d"),
        ]
        coins, manifest = pub.generate(
            rows, idx(("p1", "alpha coin", 10.0, "2026-11-20")),
            newest("p1", "2026-11-20"), {"held1": "reason"},
            set(), taxonomy_hold=None, strict_match=lambda r, p: False)
        self.assertEqual(manifest["total_input"], 5)
        self.assertEqual(len(manifest["rows"]), 5)
        by_lid = {m["listing_id"]: m["disposition"] for m in manifest["rows"]}
        self.assertEqual(by_lid["a"], "published")
        self.assertEqual(by_lid["held1"], "held")
        self.assertEqual(by_lid["c"], "incomplete")
        self.assertEqual(by_lid["d"], "pending-review")
        self.assertEqual(by_lid["b"], "pending-review")

    def test_held_rows_never_emitted(self):
        rows = [mrow("p1", "Held Thing", 5.43, "2026-11-22", "held1")]
        coins, manifest = pub.generate(
            rows, idx(("p1", "held thing", 5.43, "2026-11-22")),
            newest("p1", "2026-11-22"), {"held1": "uncertain"},
            set(), taxonomy_hold=None, strict_match=lambda r, p: True)
        self.assertEqual(coins, {})
        self.assertEqual(manifest["rows"][0]["disposition"], "held")

    def test_excluded_evidence_never_emitted(self):
        rows = [mrow("p1", "Alpha Coin", 10.0, "2026-11-20", "a")]
        coins, manifest = pub.generate(
            rows, idx(), {}, {}, {"a"},
            taxonomy_hold=None, strict_match=lambda r, p: True)
        self.assertEqual(coins, {})
        self.assertEqual(manifest["rows"][0]["reason"], "excluded-evidence")

    def test_all_emitted_rows_carry_listing_id(self):
        rows = [mrow("p1", "Alpha Coin", 10.0, "2026-11-20", "a"),
                mrow("p1", "Beta Coin", 12.0, "2026-10-01", "b")]
        coins, manifest = pub.generate(
            rows, idx(("p1", "alpha coin", 10.0, "2026-11-20")),
            newest("p1", "2026-11-20"), {}, set(),
            taxonomy_hold=None, strict_match=lambda r, p: True)
        for entry in coins.values():
            for rec in entry["products"]:
                self.assertTrue(rec["listing_id"])
        emitted = [m for m in manifest["rows"]
                   if m["disposition"] in ("published", "old-history",
                                           "approved-awaiting")]
        self.assertTrue(emitted)
        self.assertTrue(all(m["listing_id"] for m in emitted))

    def test_no_seller_or_credential_fields(self):
        rows = [mrow("p1", "Alpha Coin", 10.0, "2026-11-20", "a")]
        coins, manifest = pub.generate(
            rows, idx(("p1", "alpha coin", 10.0, "2026-11-20")),
            newest("p1", "2026-11-20"), {}, set(),
            taxonomy_hold=None, strict_match=lambda r, p: True)
        pub.assert_seller_free(coins, "test")
        pub.assert_seller_free(manifest, "test")
        with self.assertRaises(RuntimeError):
            pub.assert_seller_free({"seller_name": "x"}, "test")

    def test_newest_first_per_product(self):
        rows = [mrow("p1", "Oldie", 9.0, "2020-01-01", "old"),
                mrow("p1", "Newie", 11.0, "2026-11-20", "new")]
        coins, _ = pub.generate(
            rows, idx(), newest("p1", "2026-11-20"), {}, set(),
            taxonomy_hold=None, strict_match=lambda r, p: True)
        dates = [r["date_sold"] for r in coins["p1"]["products"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_distinct_sales_same_title_price_date_stay_distinct(self):
        rows = [mrow("p1", "Same Title", 10.0, "2026-11-20", "id-a"),
                mrow("p1", "Same Title", 10.0, "2026-11-20", "id-b")]
        coins, manifest = pub.generate(
            rows, idx(), newest("p1", "2026-11-20"), {}, set(),
            taxonomy_hold=None, strict_match=lambda r, p: True)
        self.assertEqual(len(coins["p1"]["products"]), 2)
        self.assertNotIn("duplicate-suppressed",
                         {m["disposition"] for m in manifest["rows"]})

    def test_repeat_listing_id_suppressed(self):
        rows = [mrow("p1", "Same Title", 10.0, "2026-11-20", "id-a"),
                mrow("p1", "Same Title", 10.0, "2026-11-20", "id-a")]
        coins, manifest = pub.generate(
            rows, idx(), newest("p1", "2026-11-20"), {}, set(),
            taxonomy_hold=None, strict_match=lambda r, p: True)
        self.assertEqual(len(coins["p1"]["products"]), 1)
        self.assertIn("duplicate-suppressed",
                      {m["disposition"] for m in manifest["rows"]})

    def test_taxonomy_gate_excludes(self):
        rows = [mrow("p1", "Ordinary Non-Coloured Coin", 10.0, "2026-11-20", "t")]
        coins, manifest = pub.generate(
            rows, idx(), newest("p1", "2026-11-20"), {}, set(),
            taxonomy_hold=lambda title, prod: True,
            strict_match=lambda r, p: True)
        self.assertEqual(coins, {})
        self.assertEqual(manifest["rows"][0]["reason"], "taxonomy-gate")

    def test_stripes_ambiguous_row_is_queued_not_published(self):
        rows = [mrow("s1_pnc_stripes",
                     "2024 Bluey Postal Numismatic Covers PNC $1 UNC Bluey "
                     "Coins (Uncle & Aunt)", 39.95, "2026-10-02",
                     "manual-e8b79837323098d0")]
        coins, manifest = pub.generate(
            rows, set(), {"s1_pnc_stripes": "2026-07-17"}, {}, set(),
            taxonomy_hold=lambda title, prod: False,
            strict_match=lambda r, p: False)
        self.assertEqual(coins, {})
        self.assertEqual(manifest["rows"][0]["disposition"], "pending-review")


class TestCarryOver(unittest.TestCase):
    def test_committed_only_rows_kept_verbatim(self):
        coins = {}
        committed = {"coins": {"p1": {"products": [
            {"title": "Legacy", "sale_price": 3.3,
             "date_sold": "01 Jan 2020"}]}}}
        with mock.patch("builtins.open", mock.mock_open()):
            with mock.patch("json.load", return_value=committed):
                carried = pub.carry_over_committed(coins, "x", set())
        self.assertEqual(carried, 1)
        self.assertEqual(coins["p1"]["products"][0]["title"], "Legacy")

    def test_superseded_rows_not_duplicated(self):
        coins = {"p1": {"products": [{"listing_id": "a", "title": "New",
                                      "sale_price": 1.0,
                                      "date_sold": "20 Nov 2026"}]}}
        committed = {"coins": {"p1": {"products": [
            {"listing_id": "a", "title": "New", "sale_price": 1.0,
             "date_sold": "20 Nov 2026"}]}}}
        with mock.patch("builtins.open", mock.mock_open()):
            with mock.patch("json.load", return_value=committed):
                carried = pub.carry_over_committed(coins, "x", {"a"})
        self.assertEqual(carried, 0)
        self.assertEqual(len(coins["p1"]["products"]), 1)


def _live_rows(rows):
    return {"coins": {"p1": {"ebay": {"products": rows,
                                     "historical_products": []},
                             "coinxchange": {}, "manual": {}}}}


def _live(live):
    resp = mock.MagicMock()
    resp.__enter__.return_value = resp
    return (mock.patch("urllib.request.urlopen", return_value=resp),
            mock.patch("json.load", return_value=live))


class TestVerify(unittest.TestCase):
    def test_mismatch_reported(self):
        coins = {"p1": {"products": [{"listing_id": "a", "title": "T",
                                      "sale_price": 10.0,
                                      "date_sold": "20 Nov 2026"}]}}
        live = _live_rows([{"listing_id": "a", "sale_price": 11.0,
                             "date_sold": "20 Nov 2026"}])
        uo_patch, load_patch = _live(live)
        with uo_patch, load_patch:
            result = pub.verify_against_live(coins, "https://x")
        self.assertTrue(result["errors"])

    def test_match_has_no_errors(self):
        coins = {"p1": {"products": [{"listing_id": "a", "title": "T",
                                      "sale_price": 10.0,
                                      "date_sold": "20 Nov 2026"}]}}
        live = _live_rows([{"listing_id": "a", "sale_price": 10.0,
                             "date_sold": "20 Nov 2026"},
                            {"title": "no id", "sale_price": 1.0,
                             "date_sold": "20 Nov 2026"}])
        uo_patch, load_patch = _live(live)
        with uo_patch, load_patch:
            result = pub.verify_against_live(coins, "https://x")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["live_rows_without_id"], 1)


if __name__ == "__main__":
    unittest.main()
