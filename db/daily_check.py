"""Fail-closed active eBay listing snapshot for the Bluey ledger.

Complete, product-matched snapshots upsert active listings. A disappeared
listing becomes an unconfirmed review candidate; it is never a confirmed sale.
"""
import argparse
import importlib.util
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load_project_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PRICE_API = load_project_module("bluey_prices_for_daily_check",
                                os.path.join(ROOT, "api", "prices.py"))
BUY_OPTIONS_API = load_project_module("bluey_buy_options_for_daily_check",
                                      os.path.join(ROOT, "api", "buy-options.py"))
ACTIVE_OFFERS_API = load_project_module("bluey_active_offers_for_daily_check",
                                       os.path.join(ROOT, "api", "active_offers.py"))
PRODUCTS = {str(coin.get("id")): coin for coin in PRICE_API.COINS}


def response_json(url, data=None, timeout=30):
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "BlueyCoinTracker-DailyListingCheck/3.0",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        import json
        return json.load(response), response.headers


def complete_header(headers, name):
    return str(headers.get(name, "")).strip().lower() == "true"


def tracking_mode_header(headers):
    return str(headers.get("X-Buy-Options-Mode", "")).strip().lower() == "tracking-v1"


def ebay_item_id(url):
    """Extract an item ID only from a real eBay host and item path."""
    try:
        parsed = urlsplit(str(url or ""))
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    domain = r"(?:[a-z0-9-]+\.)*ebay\.(?:com(?:\.[a-z]{2})?|co\.[a-z]{2}|[a-z]{2,})"
    if not re.fullmatch(domain, host):
        return None
    match = re.fullmatch(r"/itm/(?:[^/]+/)?([0-9]{5,20})/?", parsed.path, re.IGNORECASE)
    return match.group(1) if match else None


def ebay_items(options):
    """Return deduplicated eBay items plus item rows that cannot be trusted."""
    items = {}
    invalid = 0
    for option in options:
        if not isinstance(option, dict):
            continue
        item_id = ebay_item_id(option.get("url"))
        if item_id is None:
            continue
        if (not str(option.get("title") or option.get("name") or "").strip()
                or option.get("price") is None):
            invalid += 1
            continue
        old = items.get(item_id)
        if old and (str(old.get("title") or old.get("name") or "") !=
                    str(option.get("title") or option.get("name") or "")
                    or str(old.get("price")) != str(option.get("price"))):
            invalid += 1
            continue
        items[item_id] = option
    return items, invalid


def matches_product(title, product_id, now=None):
    """Use the same normalized live-listing gate as production discovery."""
    coin = PRODUCTS.get(str(product_id))
    if not coin:
        return False
    return PRICE_API._product_matches_live_listing(title, coin, now=now)


def uniquely_matches_product(title, product_id, now=None):
    """Reject titles that can belong to more than one canonical product."""
    aliases = BUY_OPTIONS_API.MERGED_INTO
    owners = {aliases.get(pid, pid) for pid, coin in PRODUCTS.items()
              if PRICE_API._product_matches_live_listing(title, coin, now=now)}
    return owners == {aliases.get(str(product_id), str(product_id))}


def snapshot_is_usable(prices_complete, options_complete, options, items,
                       invalid_items=0, mismatched_items=0):
    """Accept only nonempty, complete, unambiguous product snapshots."""
    if not prices_complete or not options_complete or not isinstance(options, list):
        return False
    # Even a complete empty search can reflect weak queries or upstream filtering;
    # preserve prior state until a nonempty snapshot corroborates the search.
    if not items or invalid_items or mismatched_items:
        return False
    return True


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="https://blueyco.in")
    parser.add_argument("--product-ids", help="comma-separated IDs for a bounded pilot")
    args = parser.parse_args(argv)
    try:
        import psycopg
    except ImportError:
        sys.exit("Install driver first: pip install 'psycopg[binary]'")

    db_url = os.environ.get("DATABASE_URL")
    expected_branch = os.environ.get("BLUEY_NEON_BRANCH_ID")
    if not db_url or not expected_branch:
        sys.exit("Neon DATABASE_URL and BLUEY_NEON_BRANCH_ID are required.")

    base = args.base.rstrip("/")
    try:
        prices, prices_headers = response_json(f"{base}/api/prices", timeout=30)
    except Exception as exc:
        sys.exit(f"Prices discovery failed ({type(exc).__name__}); no listing state changed.")
    if not complete_header(prices_headers, "X-Prices-Complete"):
        sys.exit("Prices discovery incomplete; no listing state changed.")
    if not isinstance(prices, dict):
        sys.exit("Prices response invalid; no listing state changed.")

    requested = None
    if args.product_ids:
        requested = {part.strip() for part in args.product_ids.split(",") if part.strip()}
        unknown = requested - set(prices)
        if unknown:
            sys.exit("Unknown product IDs: " + ", ".join(sorted(unknown)))

    aliases = BUY_OPTIONS_API.MERGED_INTO
    product_entries = {}
    for pid, entry in prices.items():
        canonical = aliases.get(pid, pid)
        if requested is not None and pid not in requested and canonical not in requested:
            continue
        if canonical not in product_entries or pid == canonical:
            product_entries[canonical] = prices.get(canonical, entry)

    try:
        conn = psycopg.connect(db_url, connect_timeout=10)
    except Exception as exc:
        sys.exit(f"Database connection failed ({type(exc).__name__}); no listing state changed.")

    schema = conn.execute(
        "SELECT to_regclass('public.products'), to_regclass('public.listings')"
    ).fetchone()
    if not schema or not all(schema):
        conn.close()
        sys.exit("Listing schema is missing; no listing state changed.")
    identity = conn.execute(
        "SELECT current_database(), current_setting('neon.branch_id', true)"
    ).fetchone()
    if identity != ("bluey", expected_branch):
        conn.close()
        sys.exit("Neon database or branch identity mismatch; no listing state changed.")

    snapshots = {}
    skipped = 0
    unresolved = 0
    for pid, entry in product_entries.items():
        if pid not in PRODUCTS:
            print(f"skip {pid}: no catalogue matcher; state preserved")
            skipped += 1
            unresolved += 1
            continue
        try:
            payload, headers = response_json(
                f"{base}/api/buy-options",
                __import__("json").dumps({"coinId": pid, "tracking": True}).encode(), timeout=60)
        except Exception as exc:
            print(f"skip {pid}: {type(exc).__name__}; state preserved")
            skipped += 1
            unresolved += 1
            continue
        options = payload.get("options") if isinstance(payload, dict) else None
        if not tracking_mode_header(headers):
            print(f"skip {pid}: production endpoint lacks tracking-v1 response marker; state preserved")
            skipped += 1
            unresolved += 1
            continue
        items, invalid = ebay_items(options) if isinstance(options, list) else ({}, 0)
        mismatched = sum(not uniquely_matches_product(
            option.get("title") or option.get("name") or "", pid)
            for option in items.values())
        usable = snapshot_is_usable(
            True, complete_header(headers, "X-Buy-Options-Complete"), options,
            items, invalid_items=invalid, mismatched_items=mismatched)
        if not usable:
            print(f"skip {pid}: incomplete, empty, ambiguous, or capped results; state preserved")
            skipped += 1
            unresolved += 1
            continue
        snapshots[pid] = {"entry": entry or {}, "items": items}

    # An item returned under multiple products is ambiguous. Preserve state for
    # every affected product rather than letting one search hide another.
    owners = {}
    conflicts = set()
    for pid, snapshot in snapshots.items():
        for item_id in snapshot["items"]:
            prior = owners.get(item_id)
            if prior is not None and prior != pid:
                conflicts.update((prior, pid))
            else:
                owners[item_id] = pid
    for pid in sorted(conflicts):
        snapshots.pop(pid, None)
        print(f"skip {pid}: item ID matched multiple products; state preserved")
        skipped += 1
        unresolved += 1

    seen_products = 0
    moved_to_review = 0
    seen_count = sum(len(snapshot["items"]) for snapshot in snapshots.values())
    try:
        with conn:
            ids = sorted(owners)
            existing = {}
            if ids:
                existing = {lid: pid for lid, pid in conn.execute(
                    "SELECT listing_id, product_id FROM listings WHERE listing_id = ANY(%s)",
                    (ids,)).fetchall()}
            db_conflicts = {pid for lid, old_pid in existing.items()
                            if lid in owners and old_pid != owners[lid]
                            for pid in (old_pid, owners[lid])}
            for pid in sorted(db_conflicts):
                snapshots.pop(pid, None)
                print(f"skip {pid}: existing item ID belongs to another product; state preserved")
                skipped += 1
                unresolved += 1

            for pid, snapshot in snapshots.items():
                try:
                    # A savepoint prevents a late uniqueness conflict from
                    # leaving a partially applied product snapshot.
                    with conn.transaction():
                        entry = snapshot["entry"]
                        items = snapshot["items"]
                        conn.execute(
                            "INSERT INTO products(product_id, name) VALUES (%s,%s) "
                            "ON CONFLICT (product_id) DO NOTHING",
                            (pid, entry.get("name") or pid))
                        for item_id, option in items.items():
                            result = conn.execute(
                                "INSERT INTO listings(listing_id, product_id, title, price_aud, "
                                "source, source_url, status) "
                                "VALUES (%s,%s,%s,%s,'browse_daily',%s,'available') "
                                "ON CONFLICT (listing_id) DO UPDATE SET "
                                "last_seen_at=now(), price_aud=EXCLUDED.price_aud, "
                                "status=CASE WHEN listings.status='confirmed_sold' "
                                "THEN 'confirmed_sold' ELSE 'available' END "
                                "WHERE listings.product_id=EXCLUDED.product_id "
                                "RETURNING listing_id",
                                (item_id, pid, option.get("title") or option.get("name") or "",
                                 option.get("price"), option.get("url") or ""))
                            if result.fetchone() is None:
                                raise RuntimeError("item ID belongs to a different product")
                        ACTIVE_OFFERS_API.persist_snapshot(
                            conn, pid, "ebay",
                            [{**option, "url": option.get("url")} for option in items.values()],
                            complete=True,
                            excluded_ids=BUY_OPTIONS_API.EXCLUDED_EBAY_ITEMS.get(pid, ()))
                        cur = conn.execute(
                            "UPDATE listings SET status='likely_sold' "
                            "WHERE product_id=%s AND status='available' "
                            "AND source='browse_daily' AND listing_id <> ALL(%s) "
                            "RETURNING listing_id",
                            (pid, list(items)))
                        moved_to_review += len(cur.fetchall())
                    seen_products += 1
                except RuntimeError as exc:
                    print(f"skip {pid}: {exc}; state preserved")
                    skipped += 1
                    unresolved += 1
    finally:
        conn.close()

    print(f"Daily check: {seen_products} products updated, {skipped} skipped; "
          f"{seen_count} unique eBay listings seen; {moved_to_review} moved to "
          f"unconfirmed review (never confirmed sold); {unresolved} products need "
          "a complete, uncapped, product-matched snapshot.")


if __name__ == "__main__":
    main()
