"""Seller-free publication generator: Melbourne ledger -> manual_ebay_sales.json.

Reads confirmed_sold rows from the authoritative Melbourne Postgres ledger
(read-only SELECTs over ssh), applies publication holds, the taxonomy gate
and the strict title matcher, and emits the committed publication shape with
a listing_id on every generated row (the current committed file has none,
which makes ID-based verification impossible).

Modes:
  --dry-run   generate to staging + manifest, never touch the committed file
  --write     overwrite the committed manual_ebay_sales.json (keeps
              committed-only rows verbatim so nothing is lost)
  --verify    compare the generated feed against live GET /api/prices by
              listing_id/product/price/date; exit 1 on any mismatch

The 2 held $5.43 rows in publication_holds.json are never emitted.
No IQR logic is changed here. No DB writes, no seller or credential fields.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import melbourne_drift as drift

DISPLAY_FMT = "%d %b %Y"

SELLER_KEY_FRAGMENTS = ("seller", "username", "email", "credential", "token",
                         "cookie", "password", "api_key", "apikey")


def _live_matchers():
    return drift._live_matchers()


def fetch_confirmed_rows():
    sql = ("SELECT row_to_json(t) FROM (SELECT product_id, title, price_aud,"
           " date_sold, listing_id, source, source_url, currency, condition,"
           " buying_format FROM listings"
           " WHERE status='confirmed_sold' AND date_sold IS NOT NULL) t;")
    rows, bad = drift.parse_json_lines(drift._ssh_psql(sql))
    if bad:
        raise RuntimeError("unparseable ledger lines: %d" % bad)
    for row in rows:
        for key in ("price_aud", "date_sold"):
            if row.get(key) is not None:
                row[key] = str(row[key])
    return rows


def fetch_excluded_evidence_ids():
    sql = ("SELECT row_to_json(t) FROM (SELECT listing_id FROM"
           " sale_import_evidence WHERE median_eligible = false"
           " AND listing_id IS NOT NULL) t;")
    rows, bad = drift.parse_json_lines(drift._ssh_psql(sql))
    if bad:
        raise RuntimeError("unparseable evidence lines: %d" % bad)
    return {str(r.get("listing_id")) for r in rows if r.get("listing_id")}


def display_date(value):
    day = drift.parse_date(str(value or ""))
    if day is None:
        return None
    return day.strftime(DISPLAY_FMT)


def build_record(row):
    """One publication row, seller-free. Returns None when undisplayable."""
    price = drift.norm_price(row.get("price_aud"))
    day = display_date(row.get("date_sold"))
    if price is None or day is None:
        return None
    rec = {
        "coin_id": (row.get("product_id") or "").strip(),
        "title": row.get("title") or "",
        "sale_price": price,
        "currency": "AU",
        "date_sold": day,
        "record_status": "AutoApproved",
        "source_type": "melbourne_confirmed_ledger",
        "listing_id": str(row.get("listing_id") or ""),
    }
    if row.get("source_url"):
        rec["link"] = row.get("source_url")
    return rec


def assert_seller_free(obj, where):
    if isinstance(obj, dict):
        for key, value in obj.items():
            lowered = str(key).lower()
            if any(frag in lowered for frag in SELLER_KEY_FRAGMENTS):
                raise RuntimeError("seller field %r in %s" % (key, where))
            assert_seller_free(value, where)
    elif isinstance(obj, list):
        for value in obj:
            assert_seller_free(value, where)


def generate(rows, json_index, json_newest, holds, excluded_ids,
             taxonomy_hold, strict_match):
    """Returns (coins, manifest). Manifest rows sum to total input.

    Ordering mirrors the serving projection: holds outrank every other
    path, so a held row already in the committed file is never emitted
    fresh (it is carried over verbatim on --write instead).
    """
    manifest_rows = []
    included = []
    seen_ids = set()
    for row in rows:
        prod = (row.get("product_id") or "").strip()
        lid = str(row.get("listing_id") or "")
        price = drift.norm_price(row.get("price_aud"))
        day = drift.parse_date(str(row.get("date_sold") or ""))
        base = {"listing_id": lid or None, "product_id": prod or None}
        if lid and lid in holds:
            manifest_rows.append(dict(base, disposition="held",
                                     reason="publication-hold"))
            continue
        if taxonomy_hold is not None and taxonomy_hold(row.get("title"), prod):
            manifest_rows.append(dict(base, disposition="held",
                                      reason="taxonomy-gate"))
            continue
        if lid and lid in excluded_ids:
            manifest_rows.append(dict(base, disposition="held",
                                      reason="excluded-evidence"))
            continue
        if price is None or day is None or not prod:
            manifest_rows.append(dict(base, disposition="incomplete",
                                      reason="missing product/price/date"))
            continue
        key = (prod, drift.norm_title(row.get("title")), price, day.isoformat())
        if key in json_index:
            disposition = "published"
            include = True
        else:
            pub_newest = json_newest.get(prod)
            if pub_newest is not None and day.isoformat() <= pub_newest:
                disposition, include = "old-history", True
            elif strict_match is not None and strict_match(row, prod):
                disposition, include = "approved-awaiting", True
            else:
                disposition, include = "pending-review", False
        if not include:
            manifest_rows.append(dict(base, disposition=disposition,
                                      reason="needs reviewer mapping"))
            continue
        if lid in seen_ids:
            manifest_rows.append(dict(base, disposition="duplicate-suppressed",
                                      reason="repeat listing_id in ledger feed"))
            continue
        rec = build_record(row)
        if rec is None:
            manifest_rows.append(dict(base, disposition="incomplete",
                                      reason="undisplayable price/date"))
            continue
        seen_ids.add(lid)
        included.append(rec)
        manifest_rows.append(dict(base, price=rec["sale_price"],
                                  date=rec["date_sold"], disposition=disposition,
                                  reason="verified Melbourne confirmed_sold"))
    coins = {}
    for rec in included:
        entry = coins.setdefault(rec["coin_id"], {"products": []})
        entry["products"].append(rec)
    for entry in coins.values():
        entry["products"].sort(key=lambda r: (r["date_sold"], r["listing_id"]),
                               reverse=True)
    manifest = {
        "batch_id": "ledger-publish-" + datetime.now().strftime("%Y%m%d-%H%M%S"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_input": len(rows),
        "rows": manifest_rows,
    }
    return coins, manifest


def carry_over_committed(coins, committed_path, melbourne_ids):
    """Keep committed rows Melbourne cannot confirm, verbatim. Returns count."""
    data = json.load(open(committed_path, encoding="utf-8"))
    carried = 0
    for cid, entry in (data.get("coins", data)).items():
        for row in entry.get("products", []):
            if not isinstance(row, dict):
                continue
            lid = str(row.get("listing_id") or row.get("item_id") or "")
            if lid and lid in melbourne_ids:
                continue
            entry_out = coins.setdefault(cid, {"products": []})
            entry_out["products"].append(dict(row))
            carried += 1
    for entry in coins.values():
        entry["products"].sort(key=lambda r: (str(r.get("date_sold")),
                                              str(r.get("listing_id"))),
                               reverse=True)
    return carried


def verify_against_live(coins, base_url):
    """Compare generated feed to live GET /api/prices. Returns error list."""
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/prices",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(request, timeout=60) as resp:
        live = json.load(resp)
    live_index = {}
    live_no_id = 0
    live_coins = live.get("coins", live)
    for cid, entry in live_coins.items():
        if not isinstance(entry, dict):
            continue
        for source in ("ebay", "coinxchange", "manual"):
            block = entry.get(source) or {}
            for key in ("products", "historical_products"):
                for row in block.get(key, []) or []:
                    lid = str((row or {}).get("listing_id") or "")
                    price = drift.norm_price((row or {}).get("sale_price"))
                    date = str((row or {}).get("date_sold") or "")
                    if not lid:
                        live_no_id += 1
                        continue
                    live_index[lid] = (cid, price, date)
    errors = []
    checked = 0
    gen_counts = {}
    live_counts = {}
    for cid, entry in live_coins.items():
        total = 0
        if isinstance(entry, dict):
            for source in ("ebay", "coinxchange", "manual"):
                block = entry.get(source) or {}
                for key in ("products", "historical_products"):
                    total += len(block.get(key, []) or [])
        live_counts[cid] = total
    for cid, entry in coins.items():
        gen_counts[cid] = len(entry["products"])
        for row in entry["products"]:
            lid = row.get("listing_id") or ""
            if not lid:
                continue
            checked += 1
            if lid not in live_index:
                errors.append({"listing_id": lid, "problem": "absent-from-live"})
                continue
            live_cid, live_price, live_date = live_index[lid]
            if live_cid != cid or live_price != row["sale_price"] or \
                    live_date != row["date_sold"]:
                errors.append({"listing_id": lid, "problem": "field-mismatch",
                               "live": [live_cid, live_price, live_date],
                               "generated": [cid, row["sale_price"],
                                             row["date_sold"]]})
    count_diff = {cid: (gen_counts.get(cid, 0), live_counts.get(cid, 0))
                  for cid in set(gen_counts) | set(live_counts)
                  if gen_counts.get(cid, 0) != live_counts.get(cid, 0)}
    return {"checked": checked, "live_rows_without_id": live_no_id,
            "errors": errors, "count_diff": count_diff}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--mode", choices=("dry-run", "write", "verify"),
                        default="dry-run")
    parser.add_argument("--live-base", default="https://blueyco.in")
    args = parser.parse_args(argv)
    committed_path = os.path.join(args.root, "manual_ebay_sales.json")
    holds = drift.load_holds(os.path.join(args.root, "publication_holds.json"))
    json_index, json_newest = drift.load_json_products(committed_path)
    taxonomy_hold, strict_match, _ = _live_matchers()
    rows = fetch_confirmed_rows()
    excluded_ids = fetch_excluded_evidence_ids()
    coins, manifest = generate(rows, json_index, json_newest, holds,
                               excluded_ids, taxonomy_hold, strict_match)
    assert_seller_free(coins, "generated feed")
    assert_seller_free(manifest, "manifest")
    accounted = len(manifest["rows"])
    if accounted != manifest["total_input"]:
        raise RuntimeError("manifest accounts %d of %d input rows"
                           % (accounted, manifest["total_input"]))
    melbourne_ids = {str(r.get("listing_id") or "") for r in rows}
    manifest["held_listing_ids"] = sorted(
        {m["listing_id"] for m in manifest["rows"]
         if m["disposition"] == "held" and m["listing_id"]})
    if args.mode in ("dry-run", "write"):
        staging = os.path.join(args.root, "staging_manual_ebay_sales.json")
        json.dump({"coins": coins}, open(staging, "w", encoding="utf-8"),
                  indent=1, ensure_ascii=False)
        manifest_path = os.path.join(args.root, "publish_manifest.json")
        json.dump(manifest, open(manifest_path, "w", encoding="utf-8"),
                  indent=2)
        print("staged: %s" % staging)
        print("manifest: %s" % manifest_path)
    if args.mode == "write":
        carried = carry_over_committed(
            coins, committed_path,
            melbourne_ids | set(manifest["held_listing_ids"]))
        manifest["carried_over_committed_only"] = carried
        json.dump({"coins": coins},
                  open(committed_path, "w", encoding="utf-8"),
                  indent=1, ensure_ascii=False)
        json.dump(manifest, open(os.path.join(args.root, "publish_manifest.json"),
                                 "w", encoding="utf-8"), indent=2)
        print("wrote: %s (carried over %d committed-only rows)"
              % (committed_path, carried))
    counts = {}
    for item in manifest["rows"]:
        counts[item["disposition"]] = counts.get(item["disposition"], 0) + 1
    print("input=%d dispositions=%s" % (manifest["total_input"], counts))
    if args.mode == "verify":
        staging = os.path.join(args.root, "staging_manual_ebay_sales.json")
        if os.path.exists(staging):
            coins = json.load(open(staging, encoding="utf-8"))["coins"]
        result = verify_against_live(coins, args.live_base)
        print("verify: checked=%d live_rows_without_id=%d errors=%d"
              % (result["checked"], result["live_rows_without_id"],
                 len(result["errors"])))
        for err in result["errors"][:20]:
            print("  MISMATCH %s" % err)
        print("per-product count diffs (generated, live): %d products"
              % len(result["count_diff"]))
        for cid in sorted(result["count_diff"])[:30]:
            print("  COUNT %s generated=%d live=%d" % (
                cid, result["count_diff"][cid][0], result["count_diff"][cid][1]))
        if result["errors"]:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
