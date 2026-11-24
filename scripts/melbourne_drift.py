"""Melbourne-to-publication drift check (read-only: SELECTs only, no DB writes).

Compares the authoritative Melbourne ledger (host Postgres `bluey`, tables
`listings` + `sale_import_evidence`) against the committed publication
artifacts (`manual_ebay_sales.json`, `publication_holds.json`) and classifies
every gap:

- published ......... Melbourne row already in the committed file
- approved-awaiting . passes holds + taxonomy + strict title gates and is
                      newer than published, but not yet in the committed file
- held .............. deliberately excluded (publication hold, taxonomy gate,
                      excluded status, or uncertain attribution)
- pending-review .... newer than anything published for that product and not
                      held or auto-approvable: needs reviewer mapping before
                      publication. The script never publishes these itself.
- old-history ....... older than the published newest: historical-only
                      coverage, not a freshness failure.
- incomplete ........ Melbourne row missing product/price/date: counted, never
                      silently skipped.

Reverse gaps (committed file vs Melbourne):

- committed-unmatched .. committed row carries a listing_id absent from
                         Melbourne (edited or orphaned row).
- committed-unverifiable committed row with no listing_id: ID-based
                         verification is impossible for these rows.

Collection gaps (per product, from listings first_seen_at/last_seen_at):

- zero-sale products ... products with no listings at all.
- collection-overdue .. products whose newest last_seen_at is older than
                         COLLECTION_OVERDUE_DAYS.

Exit 0: nothing newer than published except deliberate holds.
Exit 2: one or more pending-review rows newer than published.

Live Melbourne access shells out to ssh (alias maus-mel-a1-1) and fetches
rows as JSON (row_to_json), so titles containing "|" or newlines cannot
corrupt parsing. Unit tests exercise classify() with fixtures and never
touch the network.
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

DATE_FMTS = ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y")

COLLECTION_OVERDUE_DAYS = 7


def parse_date(value):
    for fmt in DATE_FMTS:
        try:
            return datetime.strptime((value or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def norm_title(value):
    text = (value or "").lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def norm_price(value):
    try:
        return round(float(str(value).replace("$", "").replace(",", "")), 2)
    except (TypeError, ValueError):
        return None


def parse_json_lines(text):
    """Parse row_to_json output: one JSON object per line.

    Returns (rows, unparseable_count). Robust to "|" and newlines inside
    values, which broke the old pipe-delimited parsing.
    """
    rows = []
    bad = 0
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            bad += 1
    return rows, bad


def load_json_products(path):
    data = json.load(open(path, encoding="utf-8"))
    coins = data.get("coins", data)
    index = set()
    newest = {}
    for cid, entry in coins.items():
        for row in entry.get("products", []):
            price = norm_price(row.get("sale_price"))
            day = parse_date(str(row.get("date_sold") or ""))
            if price is None or day is None:
                continue
            index.add((cid, norm_title(row.get("title")), price, day.isoformat()))
            if cid not in newest or day.isoformat() > newest[cid]:
                newest[cid] = day.isoformat()
    return index, newest


def load_json_rows(path):
    """Every committed product row, for the reverse (file-vs-Melbourne) check."""
    data = json.load(open(path, encoding="utf-8"))
    coins = data.get("coins", data)
    rows = []
    for cid, entry in coins.items():
        for row in entry.get("products", []):
            if isinstance(row, dict):
                rows.append({"coin_id": cid, "row": row})
    return rows


def load_holds(path):
    try:
        data = json.load(open(path, encoding="utf-8"))
        holds = data.get("holds") if isinstance(data, dict) else None
        return dict(holds) if isinstance(holds, dict) else {}
    except Exception:
        return {}


def classify(melbourne_rows, json_index, json_newest, holds,
             taxonomy_hold=None, strict_match=None):
    """Classify Melbourne confirmed-sold rows against the publication set.

    melbourne_rows: iterable of dicts with product_id, title, price_aud,
      date_sold (any supported format), listing_id, source.
    taxonomy_hold(title, product_id): True when a format gate holds the row.
    strict_match(row, product_id): True when the row would project as-is.

    Every input row lands in exactly one bucket; report["total_input"]
    always equals the sum of the buckets.
    """
    report = {"published": 0, "held": [], "pending_review": [],
              "approved_awaiting": [], "old_history": 0, "incomplete": [],
              "total_input": 0}
    for row in melbourne_rows:
        report["total_input"] += 1
        prod = (row.get("product_id") or "").strip()
        price = norm_price(row.get("price_aud"))
        day = parse_date(str(row.get("date_sold") or ""))
        if price is None or day is None or not prod:
            report["incomplete"].append({"row": row})
            continue
        key = (prod, norm_title(row.get("title")), price, day.isoformat())
        if key in json_index:
            report["published"] += 1
            continue
        lid = str(row.get("listing_id") or "")
        if lid and lid in holds:
            report["held"].append({"row": row, "reason": "publication-hold",
                                   "detail": holds[lid]})
            continue
        if taxonomy_hold is not None and taxonomy_hold(row.get("title"), prod):
            report["held"].append({"row": row, "reason": "taxonomy-gate"})
            continue
        pub_newest = json_newest.get(prod)
        if pub_newest is not None and day.isoformat() <= pub_newest:
            report["old_history"] += 1
            continue
        if strict_match is not None and strict_match(row, prod):
            report["approved_awaiting"].append(
                {"row": row, "published_newest": pub_newest})
            continue
        report["pending_review"].append({"row": row,
                                         "published_newest": pub_newest})
    return report


def reverse_check(committed_rows, melbourne_ids):
    """Committed rows that Melbourne cannot confirm.

    Returns {"unmatched": [...], "unverifiable": [...]}. Rows without a
    listing_id are unverifiable by ID, never silently assumed fine.
    """
    out = {"unmatched": [], "unverifiable": []}
    for item in committed_rows:
        row = item.get("row", {})
        lid = str(row.get("listing_id") or row.get("item_id") or "")
        if not lid:
            out["unverifiable"].append(item)
        elif lid not in melbourne_ids:
            out["unmatched"].append(item)
    return out


def collection_gaps(products):
    """Per-product collection health from a product listing summary.

    products: iterable of dicts with product_id, name,
      confirmed_count, max_last_seen (ISO datetime or None).
    """
    now = time.time()
    out = {"zero_sale": [], "overdue": []}
    for prod in products:
        pid = prod.get("product_id")
        if int(prod.get("confirmed_count") or 0) <= 0 and not prod.get("has_listings"):
            out["zero_sale"].append(prod)
            continue
        seen = prod.get("max_last_seen")
        try:
            age_days = (now - datetime.fromisoformat(str(seen)).timestamp()) / 86400
        except (TypeError, ValueError):
            age_days = None
        if age_days is None or age_days > COLLECTION_OVERDUE_DAYS:
            out["overdue"].append(dict(prod, age_days=age_days))
    return out


SSH_ALIAS = "maus-mel-a1-1"
PSQL = ["sudo", "-n", "-u", "postgres", "psql", "-d", "bluey", "-tA"]


def _ssh_psql(sql):
    proc = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                           SSH_ALIAS] + PSQL,
                          input=sql.encode("utf-8"), capture_output=True,
                          timeout=120)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()[-500:]
        raise RuntimeError("melbourne fetch failed: " + err)
    return proc.stdout.decode("utf-8", errors="replace")


def fetch_melbourne_confirmed_sold():
    sql = ("SELECT row_to_json(t) FROM (SELECT product_id, title, price_aud,"
           " date_sold, listing_id, source FROM listings"
           " WHERE status='confirmed_sold' AND date_sold IS NOT NULL) t;")
    rows, bad = parse_json_lines(_ssh_psql(sql))
    for row in rows:
        if row.get("price_aud") is not None:
            row["price_aud"] = str(row["price_aud"])
        for key in ("date_sold",):
            if row.get(key) is not None:
                row[key] = str(row[key])
    return rows, bad


def fetch_melbourne_products():
    sql = ("SELECT row_to_json(t) FROM (SELECT p.product_id, p.name,"
           " count(l.listing_id) FILTER (WHERE l.status='confirmed_sold')"
           " AS confirmed_count,"
           " count(l.listing_id) AS listing_count,"
           " max(l.last_seen_at) AS max_last_seen FROM products p"
           " LEFT JOIN listings l ON l.product_id = p.product_id"
           " GROUP BY p.product_id, p.name) t;")
    rows, _ = parse_json_lines(_ssh_psql(sql))
    for row in rows:
        row["has_listings"] = int(row.get("listing_count") or 0) > 0
        if row.get("max_last_seen") is not None:
            row["max_last_seen"] = str(row["max_last_seen"]).replace(" ", "T", 1)
    return rows


def fetch_melbourne_listing_ids():
    sql = "SELECT listing_id FROM listings;"
    ids = set()
    for line in _ssh_psql(sql).splitlines():
        line = line.strip()
        if line:
            ids.add(line)
    return ids


def _live_matchers():
    """Strict + taxonomy matchers wired to the serving projection code."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "api"))
    import prices as api_prices
    coins = {c["id"]: c for c in api_prices.COINS}

    def taxonomy_hold(title, prod):
        coin = coins.get(prod)
        if coin is None:
            return False
        return api_prices._reviewed_format_mismatch(title, coin)

    def strict_match(row, prod):
        coin = coins.get(prod)
        if coin is None:
            return False
        return bool(api_prices._product_matches_coin(
            {"title": row.get("title"), "date_sold": row.get("date_sold")},
            coin, now=time.time(), max_age_days=None))

    return taxonomy_hold, strict_match, api_prices


def main(argv):
    root = argv[1] if len(argv) > 1 else "."
    rows, unparseable = fetch_melbourne_confirmed_sold()
    json_index, json_newest = load_json_products(root + "/manual_ebay_sales.json")
    holds = load_holds(root + "/publication_holds.json")
    taxonomy_hold, strict_match, _ = _live_matchers()
    report = classify(rows, json_index, json_newest, holds,
                      taxonomy_hold=taxonomy_hold, strict_match=strict_match)
    if unparseable:
        report["unparseable_fetch_lines"] = unparseable
    mel_ids = fetch_melbourne_listing_ids()
    committed = load_json_rows(root + "/manual_ebay_sales.json")
    report["reverse"] = reverse_check(committed, mel_ids)
    report["collection"] = collection_gaps(fetch_melbourne_products())
    pending = report["pending_review"]
    approved = report["approved_awaiting"]
    print("melbourne confirmed_sold rows: %d" % report["total_input"])
    print("published: %d" % report["published"])
    print("approved-awaiting publication: %d" % len(approved))
    for item in approved:
        row = item["row"]
        print("  APPROVED %s %s %s %s (published newest: %s)" % (
            row["product_id"], row["date_sold"], row["price_aud"],
            (row["title"] or "")[:60], item["published_newest"]))
    print("held: %d" % len(report["held"]))
    for item in report["held"]:
        row = item["row"]
        print("  HELD [%s] %s %s %s %s" % (
            item["reason"], row["product_id"], row["date_sold"],
            row["price_aud"], (row["title"] or "")[:60]))
    print("old-history (not newer than published): %d" % report["old_history"])
    print("incomplete (missing product/price/date): %d" % len(report["incomplete"]))
    print("pending-review (newer than published): %d" % len(pending))
    for item in pending:
        row = item["row"]
        print("  PENDING %s %s %s %s (published newest: %s)" % (
            row["product_id"], row["date_sold"], row["price_aud"],
            (row["title"] or "")[:60], item["published_newest"]))
    rev = report["reverse"]
    print("committed-unmatched (listing_id absent from Melbourne): %d"
          % len(rev["unmatched"]))
    for item in rev["unmatched"][:20]:
        print("  UNMATCHED %s %s" % (item["coin_id"],
        item["row"].get("listing_id") or item["row"].get("item_id")))
    print("committed-unverifiable (no listing_id): %d" % len(rev["unverifiable"]))
    coll = report["collection"]
    print("zero-sale products: %d" % len(coll["zero_sale"]))
    for prod in coll["zero_sale"]:
        print("  ZERO-SALE %s %s" % (prod["product_id"], prod.get("name")))
    print("collection-overdue products (>%d days): %d"
          % (COLLECTION_OVERDUE_DAYS, len(coll["overdue"])))
    for prod in coll["overdue"][:20]:
        print("  OVERDUE %s last_seen=%s" % (prod["product_id"], prod.get("max_last_seen")))
    proj_held = projection_held_rows(root)
    report["projection_held"] = proj_held
    print("projection-held (committed but excluded from API): %d"
          % len(proj_held))
    for item in proj_held:
        print("  PROJ-HELD [%s] %s %s" % (
            item["reason"], item["coin"], item.get("listing_id")))
    out = root + "/melbourne_drift_report.json"
    json.dump(report, open(out, "w", encoding="utf-8"), indent=2, default=str)
    print("report: %s" % out)
    return 2 if pending else 0


def projection_held_rows(root):
    """Committed rows the serving projection deterministically excludes."""
    sys.path.insert(0, root + "/api")
    import prices as api_prices
    coins = {c["id"]: c for c in api_prices.COINS}
    data = json.load(open(root + "/manual_ebay_sales.json", encoding="utf-8"))
    holds = load_holds(root + "/publication_holds.json")
    found = []
    for cid, entry in (data.get("coins", data)).items():
        coin = coins.get(cid, {"id": cid})
        for row in entry.get("products", []):
            lid = str(row.get("listing_id") or row.get("item_id") or "")
            if lid and lid in holds:
                found.append({"coin": cid, "listing_id": lid,
                              "reason": "publication-hold"})
            elif api_prices._reviewed_format_mismatch(row.get("title"), coin):
                found.append({"coin": cid, "listing_id": lid or None,
                              "title": (row.get("title") or "")[:70],
                              "reason": "taxonomy-gate"})
    return found


if __name__ == "__main__":
    sys.exit(main(sys.argv))
