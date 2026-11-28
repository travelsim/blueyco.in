"""Regression tests for the single-use eBay listing-ID rule (2026-11-28).

Disposable-fixture tests: each class starts a throwaway Postgres container,
applies db/schema.sql, and seeds only what a case needs. Nothing here touches
Bluey production or Neon.

The rule: an eBay item ID is claimed once, ever. An ID already in the
`listings` ledger may only continue an offer that is still live for the same
product; once that offer lapses it is burned. Sold, excluded and other-product
IDs are history. Rows with no claim record (`claimed_at IS NULL`) predate the
rule and keep the old handling.

Cases:
  a. excluded ID is not restored (status and offer projection unchanged)
  b. a claimed historical ID reused on a new listing is rejected
  c. a genuinely new live ID still publishes and is claimed
  d. legacy rows with no claim record remain handled as today
  e. a live claim continues to refresh without starting a second claim
  f. a sold ID's live offer is withdrawn
"""
import importlib.util
import os
import unittest

from test_active_offers_product_scope import DisposablePostgres

ROOT = os.path.dirname(os.path.abspath(__file__))
PID = "76604949"
TITLE = "2026 Bluey Sleepytime limited edition PNC"


def _load(name, *parts):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *parts))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


daily = _load("daily_check_single_use", "db", "daily_check.py")
active = _load("active_offers_single_use", "api", "active_offers.py")


class SingleUseListingIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pg = DisposablePostgres()
        cls.conn = cls.pg.start()

    @classmethod
    def tearDownClass(cls):
        cls.pg.stop()

    def setUp(self):
        self.conn.execute("TRUNCATE active_offers, listings, products CASCADE")
        self.conn.execute(
            "INSERT INTO products(product_id,name) VALUES (%s,%s)", (PID, PID))

    # -- fixtures ---------------------------------------------------------
    def listing(self, listing_id, status="available", date_sold=None,
                claimed_at=None):
        self.conn.execute(
            "INSERT INTO listings(listing_id,product_id,title,price_aud,source,"
            "status,date_sold,claimed_at) "
            "VALUES (%s,%s,%s,%s,'browse_daily',%s,%s,%s)",
            (listing_id, PID, TITLE, 100, status, date_sold, claimed_at))

    def offer(self, listing_id, price=100, expired=False):
        self.conn.execute(
            "INSERT INTO active_offers(product_id,source,listing_id,title,"
            "price_aud,source_url,expires_at) VALUES (%s,'ebay',%s,%s,%s,%s,"
            "now() + CASE WHEN %s THEN interval '-1 hour' ELSE interval '1 day' END)",
            (PID, listing_id, TITLE, price,
             f"https://www.ebay.com.au/itm/{listing_id}", expired))

    def option(self, listing_id, price=111):
        return {"url": f"https://www.ebay.com.au/itm/{listing_id}",
                "title": TITLE, "price": price}

    def apply(self, *listing_ids, price=111):
        items = {lid: self.option(lid, price) for lid in listing_ids}
        return daily.apply_product_snapshot(self.conn, PID, {"name": PID}, items)

    def offers(self):
        return {row[0]: row[1] for row in self.conn.execute(
            "SELECT listing_id, price_aud FROM active_offers "
            "WHERE product_id=%s AND source='ebay'", (PID,)).fetchall()}

    def listing_row(self, listing_id):
        return self.conn.execute(
            "SELECT status, date_sold, claimed_at FROM listings "
            "WHERE listing_id=%s", (listing_id,)).fetchone()

    # -- (a) excluded ID is not restored ---------------------------------
    def test_excluded_id_is_not_restored(self):
        self.listing("9000001", status="excluded")
        self.offer("9000001", price=100)   # stale projection from before

        self.apply("9000001")

        status, sold, claimed = self.listing_row("9000001")
        self.assertEqual((status, sold), ("excluded", None))
        self.assertIsNone(claimed)
        self.assertEqual(self.offers(), {})

    # -- (b) claimed historical ID reused --------------------------------
    def test_claimed_historical_id_reused_on_new_listing_is_rejected(self):
        self.listing("9000002", status="likely_sold", claimed_at="2026-11-01")

        self.apply("9000002")

        status, sold, claimed = self.listing_row("9000002")
        self.assertEqual((status, sold), ("likely_sold", None))
        self.assertIsNotNone(claimed)      # the original claim survives
        self.assertEqual(self.offers(), {})

    def test_claimed_id_with_expired_offer_is_burned(self):
        self.listing("9000006", status="available", claimed_at="2026-11-01")
        self.offer("9000006", price=100, expired=True)

        self.apply("9000006")

        self.assertEqual(self.offers(), {})

    # -- (c) genuinely new ID still publishes ----------------------------
    def test_new_live_id_publishes_and_is_claimed(self):
        self.apply("9000003")

        self.assertEqual(set(self.offers()), {"9000003"})
        status, sold, claimed = self.listing_row("9000003")
        self.assertEqual((status, sold), ("available", None))
        self.assertIsNotNone(claimed)

    # -- (d) legacy row with no claim record -----------------------------
    def test_legacy_row_without_claim_record_is_handled_as_today(self):
        self.listing("9000004", status="available", claimed_at=None)

        self.apply("9000004")

        self.assertEqual(set(self.offers()), {"9000004"})
        status, sold, claimed = self.listing_row("9000004")
        self.assertEqual((status, sold), ("available", None))
        self.assertIsNotNone(claimed)      # claim starts on first publication

    def test_legacy_likely_sold_row_without_claim_is_handled_as_today(self):
        # Today a re-seen likely_sold row returns to available. Without a claim
        # record it keeps that path, so the rule is never applied backwards.
        self.listing("9000009", status="likely_sold", claimed_at=None)

        self.apply("9000009")

        self.assertEqual(set(self.offers()), {"9000009"})
        status, sold, claimed = self.listing_row("9000009")
        self.assertEqual((status, sold), ("available", None))
        self.assertIsNotNone(claimed)

    # -- (e) a live claim continues ---------------------------------------
    def test_live_claim_continues_and_refreshes_price(self):
        self.listing("9000005", status="available", claimed_at="2026-11-01")
        self.offer("9000005", price=100)

        self.apply("9000005", price=145)

        self.assertEqual(self.offers(), {"9000005": 145})
        status, _, claimed = self.listing_row("9000005")
        self.assertEqual(status, "available")
        self.assertIsNotNone(claimed)

    # -- (f) sold ID's live offer is withdrawn ----------------------------
    def test_sold_id_live_offer_is_withdrawn(self):
        self.listing("9000007", status="confirmed_sold",
                     date_sold="2026-11-23", claimed_at="2026-11-01")
        self.offer("9000007", price=288)

        self.apply("9000007")

        self.assertEqual(self.offers(), {})
        status, sold, _ = self.listing_row("9000007")
        self.assertEqual((status, str(sold)), ("confirmed_sold", "2026-11-23"))

    # -- defence in depth: the writer itself enforces the rule -----------
    def test_persist_snapshot_rejects_claimed_lapsed_id_without_daily_check(self):
        self.listing("9000008", status="likely_sold", claimed_at="2026-11-01")

        written = active.persist_snapshot(
            self.conn, PID, "ebay", [self.option("9000008")], True)

        self.assertEqual(written, 0)
        self.assertEqual(self.offers(), {})


if __name__ == "__main__":
    unittest.main()
