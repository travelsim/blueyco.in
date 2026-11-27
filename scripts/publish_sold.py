"""Seller-free publication generator: PostgreSQL ledger -> manual_ebay_sales.json.

Reads confirmed_sold rows from Melbourne over SSH or an explicitly selected
Neon branch, applies publication holds, the taxonomy gate
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
No IQR logic is changed here. The only writes are reviewer decisions
into the Melbourne review_decisions table; no listing, price, or evidence
rows are mutated, and no seller or credential fields are emitted.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import melbourne_drift as drift
import review_decisions as _reviews
import sleepytime_sold_replay as sleepytime_gate

DISPLAY_FMT = "%d %b %Y"

SELLER_KEY_FRAGMENTS = ("seller", "username", "email", "credential", "token",
                         "cookie", "password", "api_key", "apikey")


def _live_matchers():
    return drift._live_matchers()


def fetch_confirmed_rows(read_rows):
    sql = ("SELECT product_id, title, price_aud,"
           " date_sold, listing_id, source, source_url, currency, condition,"
           " buying_format FROM listings"
           " WHERE status='confirmed_sold' AND date_sold IS NOT NULL")
    rows = read_rows(sql)
    for row in rows:
        for key in ("price_aud", "date_sold"):
            if row.get(key) is not None:
                row[key] = str(row[key])
    evidence = {}
    for row in read_rows(
        "SELECT listing_id,"
        " COALESCE(raw_record->>'price_aud', raw_record->>'item_price_aud') AS item_price,"
        " COALESCE(raw_record->>'postage_aud', raw_record->>'postage') AS postage,"
        " raw_record->>'delivery_aud' AS delivery,"
        " COALESCE(raw_record->>'delivered_aud', raw_record->>'total_aud',"
        " raw_record->>'total') AS total, raw_record->>'bundle' AS bundle,"
        " raw_record->>'best_offer' AS best_offer,"
        " raw_record->>'price_basis' AS price_basis,"
        " raw_record->>'review_flag' AS review_flag FROM sale_import_evidence"
        " WHERE listing_id IS NOT NULL"
    ):
        evidence.setdefault(row["listing_id"], []).append(row)
    for row in rows:
        matching_evidence = [item for item in evidence.get(row["listing_id"], [])
                             if money_amount(item.get("item_price")) ==
                             money_amount(row["price_aud"])]
        amount = verified_postage(row["price_aud"], matching_evidence)
        if amount is None:
            # Older imports kept an explicit delivery amount in listings.condition
            # when no item-id evidence row was available. Preserve only a clear,
            # currency-marked delivery/postage amount; never infer from free text.
            match = re.fullmatch(
                r"\s*\+?\s*(?:AU\s*)?\$([\d,]+(?:\.\d{1,2})?)\s+(?:delivery|postage)\s*",
                str(row.get("condition") or ""), re.IGNORECASE)
            if match:
                amount = float(Decimal(match.group(1).replace(",", "")))
            elif re.fullmatch(
                r"\s*free\s+(?:delivery|postage)\s*",
                str(row.get("condition") or ""), re.IGNORECASE):
                amount = 0.0
        if amount is not None:
            row["shipping_price"] = amount
        for key in ("bundle", "best_offer", "price_basis", "review_flag"):
            values = {item.get(key) for item in matching_evidence
                      if item.get(key) not in (None, "")}
            if len(values) == 1:
                value = values.pop()
                if key in ("bundle", "best_offer"):
                    row[key] = value.lower() == "true"
                else:
                    row[key] = value
    return rows


def money_amount(value):
    try:
        amount = Decimal(str(value).strip().removeprefix("A$").removeprefix("$").replace(",", ""))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def verified_postage(item_price, evidence):
    item_price = money_amount(item_price)
    if item_price is None:
        return None
    amounts = set()
    for row in evidence:
        if money_amount(row["item_price"]) != item_price:
            continue
        total = money_amount(row.get("total"))
        for key in ("postage", "delivery"):
            amount = money_amount(row.get(key))
            if amount is not None and (total is None or total == item_price + amount):
                amounts.add(amount)
    if len(amounts) == 1:
        return float(amounts.pop())


def restore_cached_postage(rows, path, prices):
    with open(path, encoding="utf-8") as cache_file:
        cache = json.load(cache_file)
    evidence = {}
    for product_id, entry in cache.items():
        ebay = entry.get("ebay") or {}
        for section in ("products", "historical_products", "outliers", "historical_outliers"):
            for sale in ebay.get(section) or []:
                if str(sale.get("currency") or "").strip().upper() not in {"AU", "AUD", "A$"}:
                    continue
                day = drift.parse_date(sale.get("date_sold"))
                if day is None:
                    continue
                for listing_id in prices._sale_ids(sale):
                    evidence.setdefault((product_id, listing_id, day), []).append({
                        "item_price": sale.get("sale_price"),
                        "postage": sale.get("shipping_price"),
                        "delivery": sale.get("postage"),
                    })
    for row in rows:
        if "shipping_price" in row:
            continue
        key = (row["product_id"], row["listing_id"], drift.parse_date(row["date_sold"]))
        amount = verified_postage(row["price_aud"], evidence.get(key, []))
        if amount is not None:
            row["shipping_price"] = amount


def fetch_excluded_evidence_ids(read_rows):
    sql = ("SELECT DISTINCT listing_id FROM sale_import_evidence"
           " WHERE listing_id IS NOT NULL AND"
           " (median_eligible IS NOT TRUE OR"
           " raw_record -> 'median_eligible' = 'false'::jsonb)")
    return {str(r["listing_id"]) for r in read_rows(sql)}


def read_melbourne_rows(sql):
    rows, bad = drift.parse_json_lines(
        drift._ssh_psql("SELECT row_to_json(t) FROM (" + sql + ") t;"))
    if bad:
        raise RuntimeError("unparseable ledger lines: %d" % bad)
    return rows


def read_stored_decisions(read_rows):
    return {row["listing_id"]: (row["decision"], row["submitted_at"])
            for row in read_rows("SELECT listing_id, decision, submitted_at FROM review_decisions")}


def decision_map_for(decisions):
    result = {}
    for listing_id, (decision, _) in decisions.items():
        action, eligible, reason = _reviews.disposition_for(decision)
        result[listing_id] = dict(decision=decision, action=action,
                                  value_eligible=eligible, reason=reason)
    return result


def read_neon_ledger(mode, stored_reviews_only):
    import psycopg
    from psycopg.rows import dict_row

    url = os.environ.get("DATABASE_URL")
    branch = os.environ.get("BLUEY_NEON_BRANCH_ID")
    if not url or not branch:
        raise RuntimeError("Neon requires DATABASE_URL and BLUEY_NEON_BRANCH_ID")
    incoming = {} if stored_reviews_only else _reviews.collapse_records(_reviews.fetch_records())[0]
    with psycopg.connect(url, connect_timeout=10, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" +
                     (" READ ONLY" if mode != "write" or stored_reviews_only else ""))
        identity = conn.execute(
            "SELECT current_database() AS db, current_setting('neon.branch_id', true) AS branch"
        ).fetchone()
        if identity != {"db": "bluey", "branch": branch}:
            raise RuntimeError("Neon database or branch identity mismatch")
        read_rows = lambda sql: conn.execute(sql).fetchall()
        decided = read_stored_decisions(read_rows)
        recorded = 0
        for lid, (decision, submitted) in incoming.items():
            if lid in decided and submitted < decided[lid][1]:
                continue
            if mode == "write":
                recorded += conn.execute(
                    "INSERT INTO review_decisions (listing_id, decision, submitted_at) "
                    "VALUES (%s, %s, %s) ON CONFLICT (listing_id) DO UPDATE SET "
                    "decision=excluded.decision, submitted_at=excluded.submitted_at, "
                    "source=excluded.source, recorded_at=now() "
                    "WHERE excluded.submitted_at >= review_decisions.submitted_at "
                    "AND (excluded.decision, excluded.submitted_at) IS DISTINCT FROM "
                    "(review_decisions.decision, review_decisions.submitted_at)",
                    (lid, decision, submitted)).rowcount
            decided[lid] = (decision, submitted)
        return (fetch_confirmed_rows(read_rows), fetch_excluded_evidence_ids(read_rows),
                decided, recorded)


def display_date(value):
    day = drift.parse_date(str(value or ""))
    if day is None:
        return None
    return day.strftime(DISPLAY_FMT)


def build_record(row, value_eligible=True):
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
    if row.get("shipping_price") is not None:
        rec["shipping_price"] = row["shipping_price"]
    for key in ("bundle", "best_offer", "price_basis", "review_flag"):
        if row.get(key) not in (None, False, ""):
            rec[key] = row[key]
    if value_eligible is False:
        rec["value_eligible"] = False
    return rec


def gated_row(row, gate):
    """Apply the product gate's review flag when the row has none."""
    if gate is None or row.get("review_flag") or not gate["review_flag"]:
        return row
    return {**row, "review_flag": gate["review_flag"]}


def gate_eligible(gate, fallback=True):
    """Final value eligibility: the gate can only ever narrow it."""
    return fallback and gate["value_eligible"] if gate is not None else fallback


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
             taxonomy_hold, strict_match, decision_map=None):
    """Returns (coins, manifest). Manifest rows sum to total input.

    decision_map maps listing_id to a dict with decision/action/
    value_eligible/reason (see review_decisions.disposition_for). Reviewer
    gates never override publication holds, the taxonomy gate, or
    excluded-evidence; they decide what happens to the remaining rows.

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
        dec = decision_map.get(lid) if decision_map else None
        gate = sleepytime_gate.publication_gate(row)
        if dec is not None:
            base["review_decision"] = dec["decision"]
        if gate is not None and not gate["value_eligible"]:
            base["gate"] = gate["reason"]
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
        if dec is not None and dec["action"] in ("held", "excluded", "pending-review"):
            manifest_rows.append(dict(base, disposition=dec["action"],
                                      reason=dec["reason"]))
            continue
        if price is None or day is None or not prod:
            manifest_rows.append(dict(base, disposition="incomplete",
                                      reason="missing product/price/date"))
            continue
        if dec is not None and dec["action"] == "published":
            if lid in seen_ids:
                manifest_rows.append(dict(base, disposition="duplicate-suppressed",
                                          reason="repeat listing_id in ledger feed"))
                continue
            rec = build_record(gated_row(row, gate),
                               value_eligible=gate_eligible(
                                   gate, dec["value_eligible"]))
            if rec is None:
                manifest_rows.append(dict(base, disposition="incomplete",
                                          reason="undisplayable price/date"))
                continue
            seen_ids.add(lid)
            included.append(rec)
            manifest_rows.append(dict(
                base, price=rec["sale_price"], date=rec["date_sold"],
                disposition="published",
                reason=dec["reason"] + (
                    "; " + gate["reason"] if gate is not None else "")))
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
        rec = build_record(gated_row(row, gate),
                           value_eligible=gate_eligible(gate, True))
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


def carry_over_committed(coins, committed_path, emitted_ids,
                         dropped_ids=None):
    """Keep committed rows the fresh batch did not supersede, verbatim.

    Explicitly suppressed IDs and IDs superseded by fresh rows are skipped.
    Committed rows absent from the ledger are kept verbatim. Returns count.
    """
    data = json.load(open(committed_path, encoding="utf-8"))
    _, _, prices = _live_matchers()
    omitted_ids = set(emitted_ids) | set(dropped_ids or ())
    carried = 0
    for cid, entry in (data.get("coins", data)).items():
        for row in entry.get("products", []):
            if not isinstance(row, dict):
                continue
            if prices._sale_ids(row) & omitted_ids:
                continue
            entry_out = coins.setdefault(cid, {"products": []})
            entry_out["products"].append(dict(row))
            carried += 1
    for entry in coins.values():
        entry["products"].sort(key=lambda r: (str(r.get("date_sold")),
                                              str(r.get("listing_id"))),
                               reverse=True)
    return carried


def verify_against_live(coins, base_url, suppressed_ids=()):
    """Compare generated feed to live GET /api/prices. Returns error list."""
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/prices",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(request, timeout=60) as resp:
        live = json.load(resp)
    _, _, prices = _live_matchers()
    live_index = {}
    live_no_id = 0
    live_coins = live.get("coins", live)
    for cid, entry in live_coins.items():
        if not isinstance(entry, dict):
            continue
        for source in ("ebay", "coinxchange", "manual"):
            block = entry.get(source) or {}
            for key in ("products", "historical_products", "outliers",
                        "historical_outliers"):
                for row in block.get(key, []) or []:
                    if not isinstance(row, dict):
                        continue
                    ids = prices._sale_ids(row)
                    price = drift.norm_price(row.get("sale_price"))
                    date = drift.parse_date(str(row.get("date_sold") or ""))
                    if not ids:
                        live_no_id += 1
                    for lid in ids:
                        live_index.setdefault(lid, set()).add(
                            (cid, price, str(date), row.get("value_eligible", True),
                             prices._sold_postage(row)))
    errors = [{"listing_id": lid, "problem": "suppressed-sale-visible"}
              for lid in sorted(set(suppressed_ids) & live_index.keys())]
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
            value_eligible = row.get("value_eligible", True)
            day = str(drift.parse_date(row["date_sold"]))
            matches = live_index[lid]
            if any(actual[3] != value_eligible for actual in matches):
                errors.append({"listing_id": lid, "problem": "value-eligibility-mismatch"})
            if any(actual[4] != row.get("shipping_price") for actual in matches):
                errors.append({"listing_id": lid, "problem": "postage-mismatch"})
            if {actual[:3] for actual in matches} != {(cid, row["sale_price"], day)}:
                errors.append({"listing_id": lid, "problem": "field-mismatch",
                               "live": sorted(matches, key=str),
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
    parser.add_argument("--ledger", choices=("melbourne", "neon"), default="melbourne")
    parser.add_argument("--stored-reviews-only", action="store_true",
                        help="use stored Neon decisions only; do not fetch or write reviewer decisions")
    args = parser.parse_args(argv)
    if args.stored_reviews_only and args.ledger != "neon":
        parser.error("--stored-reviews-only requires --ledger neon")
    committed_path = os.path.join(args.root, "manual_ebay_sales.json")
    holds = drift.load_holds(os.path.join(args.root, "publication_holds.json"))
    json_index, json_newest = drift.load_json_products(committed_path)
    taxonomy_hold, strict_match, prices = _live_matchers()
    if args.ledger == "neon":
        rows, excluded_ids, decided, recorded = read_neon_ledger(
            args.mode, args.stored_reviews_only)
        decision_stats = {"records": None, "unique_listings": len(decided)}
    else:
        rows = fetch_confirmed_rows(read_melbourne_rows)
        excluded_ids = fetch_excluded_evidence_ids(read_melbourne_rows)
        _, decision_stats, recorded = _reviews.fetch_and_record()
        decided = read_stored_decisions(read_melbourne_rows)
    restore_cached_postage(rows, os.path.join(args.root, "ebay_cache.json"), prices)
    decision_map = decision_map_for(decided)
    print("decisions: unique=%d recorded=%d" % (len(decided), recorded))
    coins, manifest = generate(rows, json_index, json_newest, holds,
                               excluded_ids, taxonomy_hold, strict_match,
                               decision_map=decision_map)
    assert_seller_free(coins, "generated feed")
    assert_seller_free(manifest, "manifest")
    accounted = len(manifest["rows"])
    if accounted != manifest["total_input"]:
        raise RuntimeError("manifest accounts %d of %d input rows"
                           % (accounted, manifest["total_input"]))
    manifest["review_decisions"] = dict(decision_stats, recorded=recorded)
    manifest["held_listing_ids"] = sorted(
        {m["listing_id"] for m in manifest["rows"]
         if m["disposition"] == "held" and m["listing_id"]})
    suppressed_ids = sorted({
        m["listing_id"] for m in manifest["rows"]
        if m["listing_id"] and (
            m["disposition"] in ("held", "excluded") or
            (m["disposition"] == "pending-review" and "review_decision" in m)
        )
    })
    feed = {"coins": coins, "suppressed_listing_ids": suppressed_ids}
    if args.mode in ("dry-run", "write"):
        staging = os.path.join(args.root, "staging_manual_ebay_sales.json")
        json.dump(feed, open(staging, "w", encoding="utf-8"),
                  indent=1, ensure_ascii=False)
        manifest_path = os.path.join(args.root, "publish_manifest.json")
        json.dump(manifest, open(manifest_path, "w", encoding="utf-8"),
                  indent=2)
        print("staged: %s" % staging)
        print("manifest: %s" % manifest_path)
    if args.mode == "write":
        emitted_ids = {m["listing_id"] for m in manifest["rows"]
                       if m["disposition"] in ("published", "old-history",
                                              "approved-awaiting")
                       and m["listing_id"]}
        carried = carry_over_committed(coins, committed_path, emitted_ids,
                                       dropped_ids=set(suppressed_ids))
        manifest["carried_over_committed_only"] = carried
        json.dump(feed,
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
            with open(staging, encoding="utf-8") as staged:
                feed = json.load(staged)
        result = verify_against_live(feed["coins"], args.live_base,
                                     feed.get("suppressed_listing_ids", []))
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
