"""Read and safely refresh the independent current-offer projection."""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import psycopg

TTL = timedelta(hours=24)


def persist_snapshot(conn, product_id, source, options, complete, excluded_ids=()):
    """Upsert valid offers; incomplete input never deletes prior observations."""
    excluded = {str(x) for x in excluded_ids}
    if not complete:
        return 0
    valid = {}
    for item in options:
        url = str(item.get('url') or item.get('_tracking_url') or '')
        m = re.search(r'/itm/(\d+)', url)
        price = item.get('price')
        title = str(item.get('title') or '').strip()
        if not m or m.group(1) in excluded or not title or not isinstance(price, (int, float)):
            continue
        lid = m.group(1)
        valid[lid] = (title, price, item.get('postage'), url)
    now = datetime.now(timezone.utc)
    with conn.transaction():
        conn.execute("INSERT INTO products(product_id,name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                     (product_id, product_id))
        for lid, (title, price, postage, url) in valid.items():
            conn.execute("""INSERT INTO active_offers
                (product_id,source,listing_id,title,price_aud,postage_aud,source_url,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(product_id,source,listing_id) DO UPDATE SET
                title=EXCLUDED.title,price_aud=EXCLUDED.price_aud,
                postage_aud=EXCLUDED.postage_aud,source_url=EXCLUDED.source_url,
                last_seen_at=now(),expires_at=EXCLUDED.expires_at""",
                (product_id, source, lid, title, price, postage, url, now + TTL))
        live_ids = list(valid)
        conn.execute("DELETE FROM active_offers WHERE product_id=%s AND source=%s "
                     "AND expires_at < now()", (product_id, source))
    return len(valid)


def current_offers(conn, product_id, source=None):
    sql = "SELECT listing_id,title,price_aud,postage_aud,source_url,source FROM active_offers WHERE product_id=%s AND expires_at>now()"
    args = [product_id]
    if source:
        sql += " AND source=%s"
        args.append(source)
    return conn.execute(sql, args).fetchall()


def connect():
    url = os.environ.get('DATABASE_URL')
    return psycopg.connect(url, connect_timeout=5) if url else None
