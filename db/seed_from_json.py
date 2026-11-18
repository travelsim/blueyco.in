"""Seed the Postgres ledger from existing JSON (no new credentials needed).

Reads ebay_cache.json (RapidAPI-era sold history, still valid) and
manual_ebay_sales.json (user uploads, already validation-gated per the
extracting-secondary-market-sales-data skill), then upserts listings.

Usage: DATABASE_URL=postgresql://bluey:bluey@localhost:5432/bluey python db/seed_from_json.py
Requires: pip install psycopg[binary]
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import psycopg
except ImportError:
    sys.exit("Install driver first: pip install 'psycopg[binary]'")


def parse_date(text):
    if not text:
        return None
    for fmt in ("%d %b %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(text).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def listing_key(product_id, row):
    if row.get("item_id"):
        return str(row["item_id"])
    seed = f"{product_id}|{(row.get('title') or '').lower().strip()}|{row.get('sale_price')}|{row.get('date_sold')}"
    return "manual-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        sys.exit("DATABASE_URL not set.")
    conn = psycopg.connect(db_url)
    conn.execute(open(os.path.join(ROOT, "db", "schema.sql"), encoding="utf-8").read())
    conn.commit()

    cache = json.load(open(os.path.join(ROOT, "ebay_cache.json"), encoding="utf-8"))
    manual = json.load(open(os.path.join(ROOT, "manual_ebay_sales.json"), encoding="utf-8"))

    rows = []
    for pid, entry in cache.items():
        ebay = (entry or {}).get("ebay") or {}
        for r in (ebay.get("products") or []) + (ebay.get("historical_products") or []):
            rows.append((pid, r, "ebay_cache", "confirmed_sold"))
    for pid, entry in (manual.get("coins") or {}).items():
        for r in (entry.get("products") or []):
            rows.append((pid, r, "manual_upload", "confirmed_sold"))

    n_products = n_listings = 0
    with conn.transaction():
        for pid, r, source, status in rows:
            conn.execute(
                "INSERT INTO products(product_id, name) VALUES (%s, %s) "
                "ON CONFLICT (product_id) DO NOTHING",
                (pid, r.get("catalogue_name") or pid),
            )
            conn.execute(
                "INSERT INTO listings(listing_id, product_id, title, price_aud, "
                "date_sold, source, source_url, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (listing_id) DO UPDATE SET status=%s, last_seen_at=now()",
                (
                    listing_key(pid, r), pid, r.get("title") or "",
                    r.get("sale_price"), parse_date(r.get("date_sold")),
                    source, r.get("link"), status, status,
                ),
            )
            n_listings += 1
        n_products = conn.execute("SELECT count(*) FROM products").fetchone()[0]
    conn.commit()
    print(f"Seeded {n_products} products, upserted {n_listings} sold listings "
          f"(ebay_cache + manual_upload). Daily browse snapshots add 'available' rows next.")


if __name__ == "__main__":
    main()
