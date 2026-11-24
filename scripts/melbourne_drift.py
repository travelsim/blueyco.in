"""Melbourne-to-publication drift check (read-only by default).

Compares the authoritative Melbourne ledger (host Postgres `bluey`, tables
`listings` + `sale_import_evidence`) against the committed publication
artifacts (`manual_ebay_sales.json`, `publication_holds.json`) and classifies
every gap:

- published ......... Melbourne row already in the committed file
- held .............. deliberately excluded (publication hold, taxonomy gate,
                      excluded status, or uncertain attribution)
- pending-review .... newer than anything published for that product and not
                      held: needs reviewer mapping before publication. The
                      script never publishes these itself.
- old-history ....... older than the published newest: historical-only
                      coverage, not a freshness failure.

Exit 0: nothing newer than published except deliberate holds.
Exit 2: one or more pending-review rows newer than published.

Live Melbourne access shells out to ssh (alias maus-mel-a1-1); unit tests
exercise classify() with fixtures and never touch the network.
"""
import json
import re
import subprocess
import sys
from datetime import datetime

DATE_FMTS = ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y")


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
    """
    report = {"published": 0, "held": [], "pending_review": [],
              "old_history": 0}
    for row in melbourne_rows:
        prod = (row.get("product_id") or "").strip()
        price = norm_price(row.get("price_aud"))
        day = parse_date(str(row.get("date_sold") or ""))
        if price is None or day is None or not prod:
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
        would_project = bool(strict_match(row, prod)) if strict_match else None
        report["pending_review"].append({"row": row,
                                         "published_newest": pub_newest,
                                         "would_project_unmapped": would_project})
    return report


SSH_ALIAS = "maus-mel-a1-1"
PSQL = "sudo -n -u postgres psql -d bluey -tA"


def fetch_melbourne_confirmed_sold():
    sql = ("SELECT product_id, title, price_aud, date_sold, listing_id, source"
           " FROM listings WHERE status='confirmed_sold' AND date_sold IS NOT NULL;")
    proc = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
                           SSH_ALIAS, PSQL],
                          input=sql.encode("utf-8"), capture_output=True,
                          timeout=120)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()[-500:]
        raise RuntimeError("melbourne fetch failed: " + err)
    rows = []
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.rstrip("\n").split("|")
        if len(parts) < 6:
            continue
        rows.append({"product_id": parts[0].strip(), "title": parts[1].strip(),
                     "price_aud": parts[2].strip(), "date_sold": parts[3].strip(),
                     "listing_id": parts[4].strip(), "source": parts[5].strip()})
    return rows


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


def main(argv):
    root = argv[1] if len(argv) > 1 else "."
    rows = fetch_melbourne_confirmed_sold()
    json_index, json_newest = load_json_products(root + "/manual_ebay_sales.json")
    holds = load_holds(root + "/publication_holds.json")
    report = classify(rows, json_index, json_newest, holds)
    pending = report["pending_review"]
    print("melbourne confirmed_sold rows: %d" % len(rows))
    print("published: %d" % report["published"])
    print("held: %d" % len(report["held"]))
    for item in report["held"]:
        row = item["row"]
        print("  HELD [%s] %s %s %s %s" % (
            item["reason"], row["product_id"], row["date_sold"],
            row["price_aud"], (row["title"] or "")[:60]))
    print("old-history (not newer than published): %d" % report["old_history"])
    print("pending-review (newer than published): %d" % len(pending))
    for item in pending:
        row = item["row"]
        print("  PENDING %s %s %s %s (published newest: %s)" % (
            row["product_id"], row["date_sold"], row["price_aud"],
            (row["title"] or "")[:60], item["published_newest"]))
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


if __name__ == "__main__":
    sys.exit(main(sys.argv))
