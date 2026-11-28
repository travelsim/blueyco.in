"""Read and safely refresh the independent current-offer projection."""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import psycopg

TTL = timedelta(hours=24)
BLOCKING_STATUSES = ('confirmed_sold', 'excluded')
LISTING_URL_PATTERNS = {
    'ebay': re.compile(r'/itm/(\d+)'),
    'etsy': re.compile(r'/listing/(\d+)'),
}


def _listing_id(source, url):
    """Marketplace listing ID from a canonical item URL, or None.

    Each marketplace owns its ID namespace: an eBay item is `/itm/<id>` and an
    Etsy listing is `/listing/<id>`. The source is explicit so an eBay ID can
    never be accepted as an Etsy listing, or the reverse.
    """
    pattern = LISTING_URL_PATTERNS.get(source)
    match = pattern.search(url) if pattern else None
    return match.group(1) if match else None


def _blocked_ids(conn, product_id, source, listing_ids):
    """Listing IDs that must not be written as this product's current offers.

    A listing ID belongs to exactly one product and is claimed once, ever. The
    `listings` ledger is the owner of record, so an ID held by another product,
    already sold, or explicitly excluded is history, never a current ask.

    A ledger ID may only continue an offer that is still live for the same
    product and source. Once that offer has lapsed the ID is burned and a
    recycled ID can never start a new offer. Rows with no claim record
    (`claimed_at IS NULL`) predate this rule and are handled as before, so the
    first sweep after the rule ships does not strand every historical listing.
    """
    ids = list(listing_ids)
    if not ids:
        return set()
    live = {lid for (lid,) in conn.execute(
        "SELECT listing_id FROM active_offers WHERE listing_id = ANY(%s) "
        "AND product_id = %s AND source = %s AND expires_at > now()",
        (ids, product_id, source)).fetchall()}
    blocked = set()
    for lid, owner, status, sold, claimed in conn.execute(
            "SELECT listing_id, product_id, status, date_sold, claimed_at "
            "FROM listings WHERE listing_id = ANY(%s)", (ids,)).fetchall():
        if owner != product_id or status in BLOCKING_STATUSES or sold is not None:
            blocked.add(lid)
        elif claimed is not None and lid not in live:
            # The claim has lapsed: a recycled ID is burned, never revived.
            blocked.add(lid)
    for (lid,) in conn.execute(
            "SELECT listing_id FROM active_offers WHERE listing_id = ANY(%s) "
            "AND product_id <> %s AND expires_at > now()",
            (ids, product_id)).fetchall():
        blocked.add(lid)
    return blocked


def persist_snapshot(conn, product_id, source, options, complete, excluded_ids=()):
    """Upsert valid offers; incomplete input never deletes prior observations."""
    excluded = {str(x) for x in excluded_ids}
    if not complete:
        return 0
    valid = {}
    for item in options:
        url = str(item.get('url') or item.get('_tracking_url') or '')
        lid = _listing_id(source, url)
        price = item.get('price')
        title = str(item.get('title') or '').strip()
        if not lid or lid in excluded or not title or not isinstance(price, (int, float)):
            continue
        valid[lid] = (title, price, item.get('postage'), url)
    now = datetime.now(timezone.utc)
    with conn.transaction():
        conn.execute("INSERT INTO products(product_id,name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                     (product_id, product_id))
        blocked = _blocked_ids(conn, product_id, source, valid)
        for lid in blocked:
            valid.pop(lid, None)
        if blocked:
            # A re-seen ID whose history forbids a new claim must not keep
            # serving as this product's current ask.
            conn.execute("DELETE FROM active_offers WHERE product_id=%s AND source=%s "
                         "AND listing_id = ANY(%s)",
                         (product_id, source, sorted(blocked)))
        for lid, (title, price, postage, url) in valid.items():
            conn.execute("""INSERT INTO active_offers
                (product_id,source,listing_id,title,price_aud,postage_aud,source_url,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(product_id,source,listing_id) DO UPDATE SET
                title=EXCLUDED.title,price_aud=EXCLUDED.price_aud,
                postage_aud=EXCLUDED.postage_aud,source_url=EXCLUDED.source_url,
                last_seen_at=now(),expires_at=EXCLUDED.expires_at""",
                (product_id, source, lid, title, price, postage, url, now + TTL))
        # Publishing a live offer claims the listing ID once, ever. Every
        # later reappearance has to continue this claim, not start a new one.
        if valid:
            conn.execute("UPDATE listings SET claimed_at = now() "
                         "WHERE product_id = %s AND listing_id = ANY(%s) "
                         "AND claimed_at IS NULL",
                         (product_id, sorted(valid)))
        # A listing that has since sold or been excluded must stop serving as
        # this product's current ask, even if its cache row has not expired.
        conn.execute("DELETE FROM active_offers ao USING listings l "
                     "WHERE ao.product_id=%s AND ao.source=%s "
                     "AND l.listing_id=ao.listing_id "
                     "AND (l.status = ANY(%s) OR l.date_sold IS NOT NULL)",
                     (product_id, source, list(BLOCKING_STATUSES)))
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
