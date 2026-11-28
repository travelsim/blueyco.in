"""Current fixed-price asks per product -> asking_estimates.json.

The card's Estimated value uses matched sold sales. When a product has thin
sold evidence (fewer than three sales in the window, or nothing recent), a
single old sale is not a market: this file supplies the live Buy It Now market
instead. Lowest and median are item prices; delivered_lowest adds known
postage so the Where to Buy ranking can stay on the buyer's total.

Reads production active_offers, which the daily check refreshes. Writes one
JSON file at the repository root; it is committed with the publication so the
deployed site reads it as a static asset. No secrets are written.
"""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timezone

try:
    import psycopg
except ImportError:  # pragma: no cover - runtime guard
    sys.exit("psycopg is required: pip install -r requirements.txt")


SQL = """
    SELECT product_id, price_aud, postage_aud
    FROM active_offers
    WHERE expires_at > now()
      AND source = 'ebay'
      AND price_aud > 0
"""


def summarise(rows, now=None):
    """Group (product_id, price, postage) rows into per-product ask figures."""
    now = now or datetime.now(timezone.utc)
    grouped = {}
    for product_id, price, postage in rows:
        product_id = str(product_id or "").strip()
        if not product_id:
            continue
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        try:
            postage = float(postage) if postage is not None else None
        except (TypeError, ValueError):
            postage = None
        grouped.setdefault(product_id, []).append((price, postage))

    products = {}
    for product_id, offers in grouped.items():
        prices = sorted(price for price, _ in offers)
        delivered = sorted(
            price + (postage or 0.0) for price, postage in offers
        )
        median = statistics.median(prices)
        products[product_id] = {
            "count": len(prices),
            "lowest": round(prices[0], 2),
            "median": round(median, 2),
            # The card shows the item figure; the panel ranks by delivered.
            "value": round(median if len(prices) >= 3 else prices[0], 2),
            "delivered_lowest": round(delivered[0], 2),
            "unknown_postage": sum(1 for _, postage in offers if postage is None),
        }
    return {
        "generatedAt": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "source": "active_offers",
        "products": products,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args(argv)
    if not args.database_url:
        sys.exit("DATABASE_URL is required")

    with psycopg.connect(args.database_url) as conn:
        rows = conn.execute(SQL).fetchall()
    payload = summarise(rows)
    path = os.path.join(args.root, "asking_estimates.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
    print("wrote %s (%d products, %d offers)"
          % (path, len(payload["products"]),
             sum(p["count"] for p in payload["products"].values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
