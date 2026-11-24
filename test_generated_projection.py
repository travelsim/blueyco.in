"""Generated ledger rows must project as reviewed rows.

Melbourne confirmed_sold with an assigned product_id IS the reviewed
mapping (intake review), so publish_sold.build_record output
(source_type 'melbourne_confirmed_ledger', record_status 'AutoApproved')
must pass the serving projection's reviewed gate in api/prices.py with its
listing_id preserved. A row without the reviewed shape still respects the
strict title matcher. Fixtures only: no network, no database.
"""
import unittest
from unittest import mock

from api import prices
from scripts import publish_sold as pub

NOW = 1795488000  # 25 Nov 2026 00:00 UTC

COIN_ID = "s3_rain"
# 'silver' is not in this coin's query, so the strict matcher rejects it.
TITLE = "2026 Bluey Raining $2 Silver Coin"


def generated_row():
    melbourne_row = {"product_id": COIN_ID, "title": TITLE,
                     "price_aud": "8.90", "date_sold": "2026-11-20",
                     "listing_id": "manual-probe-1",
                     "source": "manual_upload", "source_url": None,
                     "currency": "AUD", "condition": None,
                     "buying_format": None}
    return pub.build_record(melbourne_row)


class TestGeneratedRowProjects(unittest.TestCase):
    def test_generated_row_appears_in_projection(self):
        coin = next(c for c in prices.COINS if c["id"] == COIN_ID)
        rec = generated_row()
        self.assertEqual(rec["source_type"], "melbourne_confirmed_ledger")
        self.assertEqual(rec["record_status"], "AutoApproved")
        with mock.patch.object(prices.time, "time", return_value=NOW):
            filtered = prices._quality_filter_ebay({"products": [rec]},
                                                   coin, now=NOW)
        ids = [p.get("listing_id") for p in filtered["products"]]
        self.assertIn("manual-probe-1", ids)

    def test_unreviewed_same_title_still_dropped(self):
        coin = next(c for c in prices.COINS if c["id"] == COIN_ID)
        rec = generated_row()
        rec = {k: v for k, v in rec.items()
               if k not in ("source_type", "record_status")}
        with mock.patch.object(prices.time, "time", return_value=NOW):
            filtered = prices._quality_filter_ebay({"products": [rec]},
                                                   coin, now=NOW)
        self.assertEqual(filtered["products"], [])


if __name__ == "__main__":
    unittest.main()
