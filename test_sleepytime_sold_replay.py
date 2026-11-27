"""Regression tests for the offline Sleepytime PNC sold-listing replay.

Fixtures only: no network, no database, no publication.
"""
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import sleepytime_sold_replay as replay_mod  # noqa: E402

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import server as legacy  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "buy_options", os.path.join(_ROOT, "api", "buy-options.py"))
buy_options = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(buy_options)

FIXTURE = Path(_ROOT) / "fixtures" / "sleepytime_sold_2026-11-28.json"


def load():
    fixture, observations = replay_mod.load_observations(FIXTURE)
    return fixture, observations, replay_mod.replay(
        observations, product=fixture.get("product"))


class TestSoldFixtureReplay(unittest.TestCase):
    def setUp(self):
        self.fixture, self.observations, self.report = load()
        self.by_id = {item["item_id"]: item for item in self.report["items"]}

    def test_fixture_has_the_five_evidenced_observations(self):
        self.assertEqual(len(self.observations), 5)
        self.assertEqual(
            [o["item_id"] for o in self.observations],
            ["860179205712", "267854963661", "840166097677",
             "227626858395", "377668778653"])

    def test_five_in_five_distinct_ids_out(self):
        inputs = self.report["inputs"]
        self.assertEqual(inputs["observations_in"], 5)
        self.assertEqual(inputs["distinct_item_ids"], 5)
        self.assertEqual(inputs["duplicates_removed"], 0)
        self.assertEqual(len(self.by_id), 5)

    def test_one_bundle_excluded_from_standalone_valuation(self):
        counts = self.report["counts"]
        self.assertEqual(counts["bundle"], 1)
        self.assertEqual(counts["bundle_excluded"], 1)
        bundle = self.by_id["840166097677"]
        self.assertEqual(bundle["class"], "bundle")
        self.assertFalse(bundle["confirmed_sale"])
        self.assertIsNone(bundle["write"]["price_aud"])
        self.assertIn("excluded from standalone valuation", bundle["reasons"])

    def test_one_other_configuration_held_for_review(self):
        counts = self.report["counts"]
        self.assertEqual(counts["other_configuration"], 1)
        self.assertEqual(counts["other_configuration_held"], 1)
        held = self.by_id["267854963661"]
        self.assertEqual(held["class"], "other_configuration")
        self.assertFalse(held["confirmed_sale"])
        self.assertIsNone(held["write"]["price_aud"])
        self.assertFalse(held["link_verified"])

    def test_one_best_offer_price_quarantined(self):
        counts = self.report["counts"]
        self.assertEqual(counts["price_quarantined"], 1)
        item = self.by_id["227626858395"]
        self.assertTrue(item["price_quarantined"])
        self.assertEqual(item["disclosed_item_price_aud"], 139.00)
        self.assertIsNotNone(item["quarantine_reason"])
        self.assertFalse(item["confirmed_sale"])
        self.assertIsNone(item["write"]["price_aud"])

    def test_or_best_offer_wording_alone_is_not_a_quarantined_sale(self):
        for item_id in ("267854963661", "840166097677"):
            item = self.by_id[item_id]
            self.assertTrue(item["best_offer"]["wording_present"])
            self.assertFalse(item["best_offer"]["accepted_wording"])
            self.assertFalse(item["price_quarantined"])

    def test_two_presales_flagged(self):
        counts = self.report["counts"]
        self.assertEqual(counts["presales_flagged"], 2)
        self.assertTrue(self.by_id["860179205712"]["presale"])
        self.assertTrue(self.by_id["377668778653"]["presale"])
        self.assertFalse(self.by_id["267854963661"]["presale"])

    def test_no_prices_inferred(self):
        self.assertEqual(self.report["counts"]["prices_inferred"], 0)
        for item in self.report["items"]:
            if item["write"]["price_aud"] is not None:
                self.assertEqual(
                    item["write"]["price_aud"],
                    item["disclosed_item_price_aud"])

    def test_only_two_standalone_sales_are_written(self):
        self.assertEqual(self.report["counts"]["confirmed_sale_rows"], 2)
        self.assertEqual(
            self.report["confirmed_sale_item_ids"],
            ["860179205712", "377668778653"])
        for item in self.report["items"]:
            self.assertEqual(
                item["confirmed_sale"],
                item["item_id"] in {"860179205712", "377668778653"})

    def test_summary_names_every_item_and_decision(self):
        text = "\n".join(replay_mod.summary_lines(self.report))
        for item_id in self.by_id:
            self.assertIn(item_id, text)
        for expected in ("confirmed=2", "quarantined=1", "bundle=1",
                         "other=1", "presales=2", "inferred=0"):
            self.assertIn(expected, text)


class TestDeduplication(unittest.TestCase):
    def test_repeated_item_id_is_suppressed(self):
        _, observations = replay_mod.load_observations(FIXTURE)
        duplicated = observations + [dict(observations[0])]
        report = replay_mod.replay(duplicated)
        self.assertEqual(report["inputs"]["observations_in"], 6)
        self.assertEqual(report["inputs"]["distinct_item_ids"], 5)
        self.assertEqual(report["inputs"]["duplicates_removed"], 1)
        self.assertEqual(report["counts"]["confirmed_sale_rows"], 2)


class TestDisappearanceIsNotASale(unittest.TestCase):
    def test_missing_sold_evidence_is_uncertain_and_unwritten(self):
        _, observations = replay_mod.load_observations(FIXTURE)
        observation = dict(observations[0])
        observation["sold_evidence"] = {
            "explicit": False,
            "kind": "disappeared_from_search",
            "note": "Listing no longer appears in active search.",
        }
        item = replay_mod.review(observation)
        self.assertEqual(item["class"], "uncertain")
        self.assertFalse(item["confirmed_sale"])
        self.assertIsNone(item["write"]["price_aud"])


class TestSleepytimeCatalogueAliases(unittest.TestCase):
    def test_numeric_product_and_alias_resolve_to_one_pnc(self):
        self.assertEqual(
            legacy.COIN_BY_ID["76604949"]["ebay_kw"],
            "2026 Bluey Sleepytime PNC coloured")
        self.assertEqual(
            buy_options.MERGED_INTO["s3_impressions_pnc_sleepytime"],
            "76604949")

    def test_privy_card_is_a_distinct_product(self):
        self.assertIn("Privy Mark", legacy.COIN_BY_ID["s3_sleepytime"]["ebay_kw"])
        self.assertNotEqual(
            buy_options.MERGED_INTO.get("s3_sleepytime"), "76604949")
        self.assertEqual(
            buy_options.MERGED_INTO["s3_sleepytime_privy"], "s3_sleepytime")

    def test_targeted_sold_query_variants_exist(self):
        variants = legacy.QUERY_VARIANTS["76604949"]
        self.assertEqual(len(variants), 3)
        self.assertIn("2026 Bluey Sleepytime postal numismatic cover", variants)
        for variant in variants:
            self.assertRegex(variant.lower(), r"pnc|postal")


class TestRuntimeGate(unittest.TestCase):
    PRODUCT = "76604949"

    def test_scope_is_the_one_product_and_alias(self):
        self.assertTrue(replay_mod.in_scope("76604949"))
        self.assertTrue(replay_mod.in_scope("s3_impressions_pnc_sleepytime"))
        for other in ("76604950", "", None, "s3_sleepytime"):
            self.assertFalse(replay_mod.in_scope(other))

    def test_clean_standalone_row_is_value_eligible(self):
        gate = replay_mod.listing_gate(
            self.PRODUCT, "2026 Bluey Sleepytime Limited-Edition PNC coloured $2")
        self.assertEqual(gate["class"], "standalone")
        self.assertTrue(gate["value_eligible"])
        self.assertFalse(gate["hold"])

    def test_bundle_and_other_config_are_value_ineligible(self):
        bundle = replay_mod.listing_gate(
            self.PRODUCT, "2026 $2 Bluey Sleepytime PNC IN HAND + 2 till coins")
        self.assertEqual(bundle["class"], "bundle")
        self.assertFalse(bundle["value_eligible"])
        self.assertEqual(bundle["review_flag"], "bundle")
        carded = replay_mod.listing_gate(
            self.PRODUCT,
            "2026 impressions pnc Bluey Sleepytime Colour Coin in Card")
        self.assertEqual(carded["class"], "other_configuration")
        self.assertFalse(carded["value_eligible"])

    def test_bundle_flag_alone_is_enough(self):
        gate = replay_mod.listing_gate(
            self.PRODUCT, "Bluey Sleepytime PNC", bundle=True)
        self.assertEqual(gate["class"], "bundle")
        self.assertFalse(gate["value_eligible"])

    def test_undisclosed_best_offer_is_quarantined(self):
        gate = replay_mod.listing_gate(
            self.PRODUCT, "Bluey Sleepytime Limited-Edition PNC",
            best_offer=True, review_flag="price-unconfirmed")
        self.assertFalse(gate["value_eligible"])
        self.assertEqual(gate["review_flag"], "price-unconfirmed")
        confirmed = replay_mod.listing_gate(
            self.PRODUCT, "Bluey Sleepytime Limited-Edition PNC",
            best_offer=True, review_flag="price-confirmed")
        self.assertTrue(confirmed["value_eligible"])

    def test_out_of_scope_rows_are_untouched(self):
        self.assertIsNone(replay_mod.listing_gate("76604950", "bundle job lot"))
        payload = {"products": [{"title": "bundle lot", "item_id": "x"}]}
        self.assertIs(replay_mod.gate_ebay_payload(payload, "76604950"), payload)

    def test_refresh_payload_gate_is_scoped_and_idempotent(self):
        payload = {
            "products": [
                {"title": "Bluey Sleepytime PNC + 2 extra coins",
                 "item_id": "a"},
                {"title": "Bluey Sleepytime PNC coloured",
                 "item_id": "b"},
            ],
            "historical_products": [],
        }
        once = replay_mod.gate_ebay_payload(payload, self.PRODUCT)
        self.assertFalse(once["products"][0]["value_eligible"])
        self.assertEqual(once["products"][0]["review_flag"], "bundle")
        self.assertNotIn("value_eligible", once["products"][1])
        twice = replay_mod.gate_ebay_payload(once, self.PRODUCT)
        self.assertEqual(once, twice)

    def test_other_products_keep_their_payload_in_place(self):
        payload = {"products": [{"title": "job lot", "item_id": "a"}]}
        gated = replay_mod.gate_ebay_payload(payload, "76604950")
        self.assertEqual(gated, payload)
        self.assertNotIn("value_eligible", gated["products"][0])


if __name__ == "__main__":
    unittest.main()
