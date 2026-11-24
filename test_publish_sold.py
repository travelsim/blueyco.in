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

    def test_held_rows_carried_verbatim_not_dropped(self):
        # emitted_ids mirrors main(): ids of freshly emitted rows only.
        # held1 is held (never emitted) so its committed row must be kept.
        coins = {"p1": {"products": [{"listing_id": "fresh9", "title": "New",
                                      "sale_price": 1.0,
                                      "date_sold": "20 Nov 2026"}]}}
        committed = {"coins": {"p1": {"products": [
            {"listing_id": "held1", "title": "Old", "sale_price": 5.43,
             "date_sold": "23 Nov 2026"}]}}}
        with mock.patch("builtins.open", mock.mock_open()):
            with mock.patch("json.load", return_value=committed):
                carried = pub.carry_over_committed(coins, "x", {"fresh9"})
        self.assertEqual(carried, 1)
        titles = [r["title"] for r in coins["p1"]["products"]]
        self.assertIn("Old", titles)

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


def dmap(*pairs):
    return {lid: {"decision": dec,
                    "action": pub._reviews.disposition_for(dec)[0],
                    "value_eligible": pub._reviews.disposition_for(dec)[1],
                    "reason": pub._reviews.disposition_for(dec)[2]}
            for lid, dec in pairs}


class TestReviewDecisions(unittest.TestCase):
    def _gen(self, rows, decisions, **kw):
        args = dict(json_index=set(), json_newest=newest("p1", "2026-11-20"),
                    holds={}, excluded_ids=set(), taxonomy_hold=None,
                    strict_match=lambda r, p: False, decision_map=decisions)
        args.update(kw)
        return pub.generate(rows, args["json_index"], args["json_newest"],
                            args["holds"], args["excluded_ids"],
                            args["taxonomy_hold"], args["strict_match"],
                            decision_map=args["decision_map"])

    def test_not_valid_excluded_not_emitted(self):
        rows = [mrow("p1", "Real Coin", 10.0, "2026-11-21", "a"),
                mrow("p1", "Bad Coin", 11.0, "2026-11-21", "b")]
        coins, manifest = self._gen(rows, dmap(("b", "not-valid")))
        by_lid = {m["listing_id"]: m for m in manifest["rows"]}
        self.assertEqual(by_lid["b"]["disposition"], "excluded")
        self.assertNotIn("b", [r.get("listing_id")
                                 for e in coins.values()
                                 for r in e["products"]])
        self.assertEqual(by_lid["a"]["disposition"], "pending-review")

    def test_keep_held_hidden_and_keep_pending_queued(self):
        rows = [mrow("p1", "A", 10.0, "2026-11-21", "a"),
                mrow("p1", "B", 11.0, "2026-11-21", "b")]
        coins, manifest = self._gen(
            rows, dmap(("a", "keep-held"), ("b", "keep-pending")))
        by_lid = {m["listing_id"]: m for m in manifest["rows"]}
        self.assertEqual(by_lid["a"]["disposition"], "held")
        self.assertEqual(by_lid["b"]["disposition"], "pending-review")
        self.assertEqual(coins, {})

    def test_recent_only_publishes_without_market_value(self):
        rows = [mrow("p1", "Mapped Coin", 10.0, "2026-11-21", "a")]
        coins, manifest = self._gen(rows, dmap(("a", "recent-only")))
        by_lid = {m["listing_id"]: m for m in manifest["rows"]}
        self.assertEqual(by_lid["a"]["disposition"], "published")
        self.assertEqual(by_lid["a"]["review_decision"], "recent-only")
        recs = [r for e in coins.values() for r in e["products"]]
        self.assertEqual(len(recs), 1)
        self.assertFalse(recs[0].get("value_eligible", True))

    def test_also_in_value_publishes_with_market_value(self):
        rows = [mrow("p1", "Mapped Coin", 10.0, "2026-11-21", "a")]
        coins, manifest = self._gen(rows, dmap(("a", "also-in-value")))
        recs = [r for e in coins.values() for r in e["products"]]
        self.assertEqual(len(recs), 1)
        self.assertNotIn("value_eligible", recs[0])

    def test_unknown_decision_excluded_fail_closed(self):
        rows = [mrow("p1", "A", 10.0, "2026-11-21", "a")]
        coins, manifest = self._gen(rows, dmap(("a", "keep-out")))
        by_lid = {m["listing_id"]: m for m in manifest["rows"]}
        self.assertEqual(by_lid["a"]["disposition"], "excluded")
        self.assertIn("fail closed", by_lid["a"]["reason"])
        self.assertEqual(coins, {})

    def test_publication_hold_outranks_reviewer_approval(self):
        rows = [mrow("p1", "Held Thing", 5.43, "2026-11-22", "held1")]
        coins, manifest = self._gen(
            rows, dmap(("held1", "also-in-value")), holds={"held1": "x"})
        by_lid = {m["listing_id"]: m for m in manifest["rows"]}
        self.assertEqual(by_lid["held1"]["disposition"], "held")
        self.assertEqual(coins, {})

    def test_manifest_still_accounts_every_row(self):
        rows = [mrow("p1", "A", 10.0, "2026-11-21", "a"),
                mrow("p1", "B", 11.0, "2026-11-21", "b"),
                mrow("p1", "C", 12.0, "2026-11-21", "c")]
        coins, manifest = self._gen(
            rows, dmap(("a", "not-valid"), ("b", "keep-pending"),
                       ("c", "recent-only")))
        self.assertEqual(manifest["total_input"], 3)
        self.assertEqual(len(manifest["rows"]), 3)


class TestCarryOverReviewerExclusions(unittest.TestCase):
    def test_excluded_rows_purged_held_rows_kept(self):
        import tempfile, os as _os
        committed = {"coins": {"p1": {"products": [
            {"coin_id": "p1", "title": "Held", "sale_price": 5.0,
             "date_sold": "20 Nov 2026", "listing_id": "held1"},
            {"coin_id": "p1", "title": "Bad", "sale_price": 6.0,
             "date_sold": "20 Nov 2026", "listing_id": "bad1"},
            {"coin_id": "p1", "title": "Legacy", "sale_price": 7.0,
             "date_sold": "20 Nov 2026"},
        ]}}}
        with tempfile.TemporaryDirectory() as tmp:
            path = _os.path.join(tmp, "manual_ebay_sales.json")
            json.dump(committed, open(path, "w", encoding="utf-8"))
            coins = {}
            carried = pub.carry_over_committed(
                coins, path, set(), dropped_ids={"bad1"})
            kept = [r.get("listing_id") for e in coins.values()
                    for r in e["products"]]
            self.assertIn("held1", kept)
            self.assertNotIn("bad1", kept)
            # legacy row without an id is preserved verbatim
            self.assertEqual(len(kept), 2)
            self.assertEqual(carried, 2)
