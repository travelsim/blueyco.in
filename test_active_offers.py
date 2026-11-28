import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location("active_offers", os.path.join(ROOT, "api", "active_offers.py"))
active = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(active)


class ActiveOffersImportTests(unittest.TestCase):
    def test_package_import_used_by_buy_options_resolves(self):
        """buy-options.py does `from api import active_offers`; a hyphenated
        filename raises ModuleNotFoundError and silently drops the projection."""
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from api import active_offers
        self.assertTrue(callable(active_offers.persist_snapshot))
        self.assertTrue(callable(active_offers.current_offers))


class FakeTransaction:
    def __enter__(self): return self
    def __exit__(self, *args): return False


class FakeConnection:
    def __init__(self): self.calls = []
    def transaction(self): return FakeTransaction()
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self
    def fetchall(self): return []
    def fetchone(self): return None


class ActiveOfferTests(unittest.TestCase):
    def test_incomplete_snapshot_preserves_every_prior_row(self):
        conn = FakeConnection()
        self.assertEqual(active.persist_snapshot(conn, 'p', 'ebay', [], False), 0)
        self.assertEqual(conn.calls, [])

    def test_dedupes_and_excludes_before_upsert_and_expiry_only(self):
        conn = FakeConnection()
        rows = [
            {'url':'https://ebay.com.au/itm/123456','title':'Bluey coin','price':12},
            {'url':'https://ebay.com.au/itm/123456','title':'Bluey coin revised','price':13},
            {'url':'https://ebay.com.au/itm/222222','title':'excluded','price':1},
            {'url':'https://example.org/item','title':'no marketplace id','price':1},
        ]
        self.assertEqual(active.persist_snapshot(conn,'p','ebay',rows,True,['222222']),1)
        sql = '\n'.join(call[0] for call in conn.calls)
        self.assertIn('ON CONFLICT(product_id,source,listing_id)', sql)
        self.assertIn('expires_at < now()', sql)
        self.assertEqual(sum('INSERT INTO active_offers' in call[0] for call in conn.calls),1)
        self.assertIn('Bluey coin revised', str(conn.calls))


if __name__ == '__main__': unittest.main()
