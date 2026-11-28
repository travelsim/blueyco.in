"""Product-scope safety tests for the active-offer writer (api/active_offers.py).

These are disposable-fixture tests: each run starts a throwaway Postgres
container, applies db/schema.sql, and seeds only what a case needs. Nothing
here touches the Bluey production database.

Cases required by the 2026-11-28 live-offer repair:
  1. same-ID          - one eBay item ID may belong to one product only
  2. sold-history     - a sold listing must never be written as a live offer,
                        and a stale offer for a newly sold listing is withdrawn
  3. exclusion        - supplied exclusion IDs are never written
  4. unrelated-record - a product sweep never edits another product's rows

If Docker is unavailable (for example in CI) the class skips rather than
failing; the SQL-shape unit tests in test_active_offers.py still run.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import time
import unittest
import uuid

import psycopg

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location(
    "active_offers_product_scope", os.path.join(ROOT, "api", "active_offers.py"))
active = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(active)

CONTAINER_PREFIX = "bluey-ao-fixture"


def _docker():
    exe = shutil.which("docker")
    if not exe:
        return None
    try:
        probe = subprocess.run([exe, "image", "inspect", "postgres:16-alpine"],
                               capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    return exe if probe.returncode == 0 else None


def _run(exe, *args, **kwargs):
    return subprocess.run([exe, *args], capture_output=True, text=True,
                          timeout=kwargs.pop("timeout", 120), **kwargs)


class DisposablePostgres:
    """A throwaway postgres:16-alpine container with the Bluey schema applied."""

    def __init__(self):
        self.exe = _docker()
        if not self.exe:
            raise unittest.SkipTest(
                "docker with postgres:16-alpine unavailable; "
                "product-scope fixture tests need a disposable Postgres")
        self.name = f"{CONTAINER_PREFIX}-{uuid.uuid4().hex[:10]}"
        self.conn = None

    def start(self):
        try:
            started = _run(self.exe, "run", "-d", "--rm", "--name", self.name,
                           "-e", "POSTGRES_PASSWORD=blueyfixture",
                           "-e", "POSTGRES_DB=bluey_test",
                           "-p", "127.0.0.1::5432",
                           "postgres:16-alpine",
                           "-c", "fsync=off", "-c", "synchronous_commit=off")
            if started.returncode != 0:
                raise RuntimeError(
                    f"container start failed: {started.stderr.strip()[:300]}")
            deadline = time.time() + 90
            while time.time() < deadline:
                try:
                    ready = _run(self.exe, "exec", self.name, "pg_isready",
                                 "-U", "postgres", "-d", "bluey_test", timeout=15)
                except subprocess.TimeoutExpired:
                    ready = None
                if ready is not None and ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("disposable Postgres did not become ready")
            ports = _run(self.exe, "port", self.name, "5432/tcp").stdout.strip()
            host, port = ports.rsplit(":", 1)
            self.conn = psycopg.connect(host=host, port=int(port), user="postgres",
                                        password="blueyfixture", dbname="bluey_test",
                                        autocommit=True, connect_timeout=10)
            with open(os.path.join(ROOT, "db", "schema.sql"), encoding="utf-8") as fh:
                self.conn.execute(fh.read())
        except BaseException:
            self.stop()
            raise
        return self.conn

    def stop(self):
        try:
            if self.conn is not None:
                self.conn.close()
        finally:
            if self.exe:
                _run(self.exe, "rm", "-f", self.name, timeout=60)


class ProductScopedWriterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pg = DisposablePostgres()
        cls.conn = cls.pg.start()

    @classmethod
    def tearDownClass(cls):
        cls.pg.stop()

    def setUp(self):
        self.conn.execute("TRUNCATE active_offers, listings, products CASCADE")

    # -- fixtures ---------------------------------------------------------
    def product(self, pid, name=None):
        self.conn.execute("INSERT INTO products(product_id,name) VALUES (%s,%s)",
                          (pid, name or pid))

    def listing(self, listing_id, pid, status="available", date_sold=None,
                price=10):
        self.conn.execute(
            "INSERT INTO listings(listing_id,product_id,title,price_aud,source,"
            "status,date_sold) VALUES (%s,%s,%s,%s,'browse_daily',%s,%s)",
            (listing_id, pid, f"listing {listing_id}", price, status, date_sold))

    def offer(self, pid, listing_id, price=10, expired=False):
        self.conn.execute(
            "INSERT INTO active_offers(product_id,source,listing_id,title,price_aud,"
            "source_url,expires_at) VALUES (%s,'ebay',%s,%s,%s,%s,"
            "now() + CASE WHEN %s THEN interval '-1 hour' ELSE interval '1 day' END)",
            (pid, listing_id, f"listing {listing_id}", price,
             f"https://www.ebay.com.au/itm/{listing_id}", expired))

    def option(self, listing_id, price=10):
        return {"url": f"https://www.ebay.com.au/itm/{listing_id}",
                "title": f"listing {listing_id}", "price": price}

    def offers(self, pid):
        return {row[0]: row[1] for row in self.conn.execute(
            "SELECT listing_id, price_aud FROM active_offers "
            "WHERE product_id=%s AND source='ebay'", (pid,)).fetchall()}

    # -- case 1: same-ID --------------------------------------------------
    def test_same_id_owned_by_another_product_is_not_written(self):
        self.product("product_a")
        self.product("product_b")
        self.listing("111", "product_a")
        self.offer("product_a", "111", price=50)

        written = active.persist_snapshot(
            self.conn, "product_b", "ebay", [self.option("111", 99)], True)

        self.assertEqual(written, 0)
        self.assertEqual(self.offers("product_b"), {})
        self.assertEqual(self.offers("product_a"), {"111": 50})

    def test_same_id_repeated_in_one_snapshot_writes_one_row(self):
        self.product("product_a")
        self.listing("222", "product_a")

        written = active.persist_snapshot(
            self.conn, "product_a", "ebay",
            [self.option("222", 10), self.option("222", 12)], True)

        self.assertEqual(written, 1)
        self.assertEqual(self.offers("product_a"), {"222": 12})

    # -- case 2: sold-history ---------------------------------------------
    def test_confirmed_sold_listing_is_not_written_as_a_live_offer(self):
        self.product("product_a")
        self.listing("333", "product_a", status="confirmed_sold",
                     date_sold="2026-09-09", price=229.95)

        written = active.persist_snapshot(
            self.conn, "product_a", "ebay", [self.option("333", 229.95)], True)

        self.assertEqual(written, 0)
        self.assertEqual(self.offers("product_a"), {})
        status, sold = self.conn.execute(
            "SELECT status, date_sold FROM listings WHERE listing_id='333'").fetchone()
        self.assertEqual((status, str(sold)), ("confirmed_sold", "2026-09-09"))

    def test_stale_offer_is_withdrawn_when_its_listing_is_now_sold(self):
        self.product("product_a")
        self.listing("444", "product_a", status="confirmed_sold",
                     date_sold="2026-11-23", price=288)
        self.offer("product_a", "444", price=288)
        self.listing("445", "product_a")

        active.persist_snapshot(
            self.conn, "product_a", "ebay", [self.option("445", 20)], True)

        self.assertEqual(self.offers("product_a"), {"445": 20})
        self.assertEqual(self.conn.execute(
            "SELECT status FROM listings WHERE listing_id='444'").fetchone()[0],
            "confirmed_sold")

    # -- case 3: exclusion ------------------------------------------------
    def test_excluded_id_is_skipped_while_valid_rows_are_written(self):
        self.product("product_a")
        self.listing("555", "product_a")
        self.listing("556", "product_a")

        written = active.persist_snapshot(
            self.conn, "product_a", "ebay",
            [self.option("555", 5), self.option("556", 6)], True,
            excluded_ids=["555"])

        self.assertEqual(written, 1)
        self.assertEqual(self.offers("product_a"), {"556": 6})

    # -- case 4: unrelated-record ----------------------------------------
    def test_sweep_edits_only_its_own_product_source_and_expired_rows(self):
        self.product("product_a")
        self.product("product_b")
        self.listing("661", "product_a")
        self.listing("662", "product_a")
        self.listing("663", "product_b")
        self.offer("product_a", "661", price=11)                    # fresh, keep
        self.offer("product_a", "662", price=12, expired=True)      # expired, drop
        self.offer("product_b", "663", price=13)                    # unrelated, keep

        written = active.persist_snapshot(
            self.conn, "product_a", "ebay", [self.option("661", 15)], True)

        self.assertEqual(written, 1)
        self.assertEqual(self.offers("product_a"), {"661": 15})
        self.assertEqual(self.offers("product_b"), {"663": 13})
        self.assertEqual(self.conn.execute(
            "SELECT product_id FROM listings WHERE listing_id='663'").fetchone()[0],
            "product_b")


if __name__ == "__main__":
    unittest.main()
