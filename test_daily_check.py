import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location("daily_check", os.path.join(ROOT, "db", "daily_check.py"))
daily_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(daily_check)


class TestDailyListingSnapshot(unittest.TestCase):
    def setUp(self):
        self.options = [
            {"url": "https://www.ebay.com.au/itm/12345?hash=x", "title": "2024 $1 Bluey Dollarbuck coin", "price": 25},
            {"url": "https://www.ebay.com.au/sch/i.html?_nkw=Bluey", "title": "search", "price": None},
            {"url": "https://example.com/item", "title": "other retailer", "price": 10},
        ]

    def test_only_official_ebay_item_urls_are_identified(self):
        items, invalid = daily_check.ebay_items(self.options)
        self.assertEqual(list(items), ["12345"])
        self.assertEqual(invalid, 0)

    def test_lookalike_host_and_search_result_do_not_become_items(self):
        self.assertIsNone(daily_check.ebay_item_id("https://ebay.com.attacker.example/itm/12345"))
        self.assertIsNone(daily_check.ebay_item_id("https://example.com/itm/12345?next=ebay.com.au"))
        self.assertIsNone(daily_check.ebay_item_id("https://www.ebay.com.au/sch/i.html?_nkw=Bluey"))

    def test_duplicate_id_conflict_is_invalid(self):
        options = [
            {"url": "https://www.ebay.com.au/itm/12345", "title": "2024 Bluey Dollarbuck coin", "price": 25},
            {"url": "https://www.ebay.com.au/itm/12345?other=1", "title": "2024 Bluey Dollarbuck coin", "price": 26},
        ]
        items, invalid = daily_check.ebay_items(options)
        self.assertEqual(invalid, 1)

    def test_complete_tracking_snapshot_accepts_more_than_shopper_cap(self):
        options = [
            {"url": f"https://www.ebay.com.au/itm/{12345 + i}",
             "title": "2024 $1 Bluey Dollarbuck coin", "price": 25}
            for i in range(12)
        ]
        items, invalid = daily_check.ebay_items(options)
        self.assertTrue(daily_check.snapshot_is_usable(True, True, options, items, invalid))

    def test_empty_snapshot_preserves_existing_state(self):
        self.assertFalse(daily_check.snapshot_is_usable(True, True, [], {}))
        self.assertFalse(daily_check.snapshot_is_usable(True, False, [], {}))

    def test_old_shopper_endpoint_cannot_masquerade_as_empty_tracking_snapshot(self):
        self.assertFalse(daily_check.tracking_mode_header({
            "X-Buy-Options-Complete": "true",
        }))
        self.assertTrue(daily_check.tracking_mode_header({
            "X-Buy-Options-Complete": "true",
            "X-Buy-Options-Mode": "tracking-v1",
        }))

    def test_partial_empty_and_mismatched_snapshots_preserve_state(self):
        items, invalid = daily_check.ebay_items(self.options)
        self.assertFalse(daily_check.snapshot_is_usable(False, True, self.options, items))
        self.assertFalse(daily_check.snapshot_is_usable(True, False, self.options, items))
        self.assertFalse(daily_check.snapshot_is_usable(True, True, self.options, items,
                                                         mismatched_items=1))

    def test_strict_product_match_rejects_nearby_variant(self):
        self.assertTrue(daily_check.matches_product("2024 $1 Bluey Dollarbuck coin", "s1_bluey"))
        self.assertFalse(daily_check.matches_product("2024 $1 Bingo Dollarbuck coin", "s1_bluey"))

    def test_sleepytime_packaging_distinctions(self):
        self.assertFalse(daily_check.matches_product(
            "2026 Bluey Sleepytime stamp and pin cover", "s3_sleepytime_insert"))
        self.assertFalse(daily_check.matches_product(
            "2026 Bluey Sleepytime maxicard", "s3_sleepytime_insert"))
        self.assertTrue(daily_check.matches_product(
            "2026 Bluey Sleepytime limited edition PNC", "76604949"))
        self.assertFalse(daily_check.matches_product(
            "2026 Bluey Sleepytime stamp and pin cover", "76604949"))

    def test_ambiguous_title_does_not_enter_snapshot(self):
        self.assertFalse(daily_check.uniquely_matches_product(
            "2026 $2 Bluey Sleepytime coloured coin", "s3_sleepytime_insert"))
        self.assertTrue(daily_check.uniquely_matches_product(
            "2026 Bluey Sleepytime limited edition PNC", "76604949"))

    def test_plain_uncirculated_title_belongs_to_bluey_only(self):
        # A plain coin title used to match the coloured Bluey, Heelers and
        # Grannies cards as well, which made every s1_bluey snapshot ambiguous.
        for title in (
            "2024 $1 Bluey Dollarbuck coin",
            "2024 $1 Dollar Bluey DollarBucks - Bluey with baloon",
            "2024 $1 Bluey Dollarbucks Uncirculated One Dollar Coin Bucks",
        ):
            self.assertTrue(daily_check.uniquely_matches_product(title, "s1_bluey"), title)
            for coloured in ("s1_coloured_bluey", "s1_coloured_heelers", "s1_coloured_grannies"):
                self.assertFalse(daily_check.uniquely_matches_product(title, coloured), title)

    def test_colour_finish_is_required_and_spelling_is_one_family(self):
        for title in (
            "2024 Bluey Coloured Uncirculated Dollarbuck Coin Bluey card",
            "2024 Bluey Color Uncirculated Dollarbuck Coin Bluey card",
            "2024 Bluey Colour Uncirculated Dollarbuck Coin Bluey card",
        ):
            self.assertTrue(daily_check.uniquely_matches_product(title, "s1_coloured_bluey"), title)
            self.assertFalse(daily_check.matches_product(title, "s1_bluey"), title)
        # A colour title that names no character cannot be attributed.
        self.assertFalse(daily_check.uniquely_matches_product(
            "2024 Bluey Colour Uncirculated Dollarbuck Coin", "s1_coloured_bluey"))

    def test_silver_and_proof_finishes_do_not_need_the_colour_word(self):
        self.assertTrue(daily_check.uniquely_matches_product(
            "2024 $1 Bluey Dollarbucks Fine Silver Proof Coin", "s1_proof_silver"))

    def test_sold_record_gate_is_unchanged_by_the_live_colour_rule(self):
        # The release is scoped to live matching: a sold record that a coloured
        # product used to accept must still be accepted, otherwise a deploy
        # could move a published median on its own.
        from datetime import datetime, timezone
        from api import prices
        now = datetime(2026, 11, 28, tzinfo=timezone.utc).timestamp()
        sold = {"title": "2024 Bluey Dollarbuck Uncirculated One Dollar Coin",
                "date_sold": "20 Nov 2026"}
        coin = daily_check.PRODUCTS["s1_coloured_bluey"]
        self.assertTrue(prices._product_matches_coin(sold, coin, now=now))
        self.assertFalse(prices._product_matches_live_listing(sold["title"], coin, now=now))
        # A plain product still rejects a sold record that claims the finish.
        plain = daily_check.PRODUCTS["s1_bluey"]
        coloured_sold = {"title": "2024 Bluey Coloured Dollarbuck Coin",
                         "date_sold": "20 Nov 2026"}
        self.assertFalse(prices._product_matches_coin(coloured_sold, plain, now=now))

    def test_live_match_normalizes_seller_wording_and_rejects_quantity_lots(self):
        self.assertTrue(daily_check.matches_product(
            "2024 $1 Bluey Dollarbucks Uncirculated One Dollar Coin Bucks", "s1_bluey"))
        self.assertFalse(daily_check.matches_product(
            "2024 Bluey Dollarbucks Coins In Cards, 3 Individual coins", "s1_bluey"))
        self.assertFalse(daily_check.matches_product(
            "2024 Bluey Dollarbucks Colorized MS69 PCGS", "s1_bluey"))
        self.assertFalse(daily_check.matches_product(
            "2024 Dollarbucks $1 Bluey + Bingo Coins Uncirculated One Dollar Coin", "s1_bingo"))

    def test_live_discovery_and_checker_share_exact_same_gate(self):
        from api import prices
        for pid, title in [
            ("s1_bluey", "2024 $1 Bluey Dollarbucks Uncirculated One Dollar Coin Bucks"),
            ("s1_bluey", "2024 Bluey Dollarbucks Coins In Cards, 3 Individual coins"),
            ("s1_bingo", "2024 $1 BLUEY DOLLARBUCKS BINGO COIN CIRCULATED."),
            ("s1_bingo", "2024 Dollarbucks $1 Bluey + Bingo Coins Uncirculated One Dollar Coin"),
        ]:
            self.assertEqual(daily_check.matches_product(title, pid),
                             prices._product_matches_live_listing(
                                 title, daily_check.PRODUCTS[pid]))


if __name__ == "__main__":
    unittest.main()
