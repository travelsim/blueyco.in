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

    def test_combined_ten_result_cap_is_rejected_even_with_fewer_ebay_rows(self):
        options = [dict(self.options[0], url=f"https://retailer{i}.example/item", price=25)
                   for i in range(9)] + [self.options[0]]
        items, invalid = daily_check.ebay_items(options)
        self.assertFalse(daily_check.snapshot_is_usable(True, True, options, items, invalid))

    def test_five_items_are_not_the_endpoint_cap(self):
        options = [
            {"url": f"https://www.ebay.com.au/itm/{12345 + i}",
             "title": "2024 $1 Bluey Dollarbuck coin", "price": 25}
            for i in range(5)
        ]
        items, invalid = daily_check.ebay_items(options)
        self.assertTrue(daily_check.snapshot_is_usable(True, True, options, items, invalid))

    def test_full_ten_item_ebay_cap_is_rejected(self):
        options = [
            {"url": f"https://www.ebay.com.au/itm/{12345 + i}",
             "title": "2024 $1 Bluey Dollarbuck coin", "price": 25}
            for i in range(10)
        ]
        items, invalid = daily_check.ebay_items(options)
        self.assertFalse(daily_check.snapshot_is_usable(True, True, options, items, invalid))

    def test_partial_empty_and_mismatched_snapshots_preserve_state(self):
        items, invalid = daily_check.ebay_items(self.options)
        self.assertFalse(daily_check.snapshot_is_usable(False, True, self.options, items))
        self.assertFalse(daily_check.snapshot_is_usable(True, False, self.options, items))
        self.assertFalse(daily_check.snapshot_is_usable(True, True, [], {}))
        self.assertFalse(daily_check.snapshot_is_usable(True, True, self.options, items,
                                                         mismatched_items=1))

    def test_strict_product_match_rejects_nearby_variant(self):
        self.assertTrue(daily_check.matches_product("2024 $1 Bluey Dollarbuck coin", "s1_bluey"))
        self.assertFalse(daily_check.matches_product("2024 $1 Bingo Dollarbuck coin", "s1_bluey"))


if __name__ == "__main__":
    unittest.main()
