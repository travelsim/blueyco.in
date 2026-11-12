"""Daily available-listing check (no RapidAPI).

Re-fetches active eBay listings via the existing /api/buy-options endpoint
(Browse API with EBAY_CLIENT_ID/SECRET), upserts them as 'available',
then marks any 'available' row not seen today as 'likely_sold' so the
human can verify it and upload the result (which flips it to confirmed_sold).

Usage: DATABASE_URL=... python db/daily_check.py [base_url=https://blueyco.in]
Requires: pip install 'psycopg[binary]'
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    import psycopg
except ImportError:
    sys.exit("Install driver first: pip install 'psycopg[binary]'")


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "https://blueyco.in"
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        sys.exit("DATABASE_URL not set.")
    conn = psycopg.connect(db_url)
    conn.execute(open(os.path.join(ROOT, "db", "schema.sql"), encoding="utf-8").read())
    conn.commit()

    prices = json.load(urllib.request.urlopen(
        urllib.request.Request(f"{base}/api/prices",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) blueyco-in-daily-check"}),
        timeout=30))
    # /api/prices returns {coin_id: entry} directly (no list wrapper).
    coin_ids = list(prices.keys()) if isinstance(prices, dict) else [c.get("id") for c in prices]
    seen_ids = set()
    with conn.transaction():
        for pid in coin_ids:
            entry = prices.get(pid) if isinstance(prices, dict) else {}
            if not pid:
                continue
            conn.execute(
                "INSERT INTO products(product_id, name) VALUES (%s,%s) "
                "ON CONFLICT (product_id) DO NOTHING",
                (pid, (entry or {}).get("name") or pid),
            )
            req = urllib.request.Request(
                f"{base}/api/buy-options",
                data=json.dumps({"coinId": pid}).encode(),
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) blueyco-in-daily-check"},
            )
            try:
                options = json.load(urllib.request.urlopen(req, timeout=60))
            except Exception as e:
                print(f"skip {pid}: {e}")
                continue
            for opt in (options if isinstance(options, list) else options.get("options", [])):
                url = opt.get("url") or ""
                item = url.split("/itm/")[-1].split("?")[0].split("&")[0] if "/itm/" in url else None
                lid = item or f"live-{pid}-{abs(hash(url + str(opt.get('price')))) % 10**12}"
                conn.execute(
                    "INSERT INTO listings(listing_id, product_id, title, price_aud, "
                    "source, source_url, status) VALUES (%s,%s,%s,%s,'browse_daily',%s,'available') "
                    "ON CONFLICT (listing_id) DO UPDATE SET last_seen_at=now(), "
                    "price_aud=EXCLUDED.price_aud, status=CASE WHEN listings.status='confirmed_sold' THEN 'confirmed_sold' ELSE 'available' END",
                    (lid, pid, opt.get("title") or opt.get("name") or "",
                     opt.get("price"), url),
                )
                seen_ids.add(lid)
        cur = conn.execute(
            "UPDATE listings SET status='likely_sold' "
            "WHERE status='available' AND last_seen_at < date_trunc('day', now()) "
            "RETURNING listing_id"
        )
        moved = cur.fetchall()
    conn.commit()
    print(f"Daily check: {len(seen_ids)} active listings seen; "
          f"{len(moved)} newly likely_sold (see view likely_sold_queue).")


if __name__ == "__main__":
    main()
