"""Offline replay of the 2026 Bluey Sleepytime PNC sold observations.

Single product pilot for the sold-listing ingest path. Reads a fixture of eBay
sold-search observations, deduplicates by marketplace item ID, classifies each
item conservatively, and decides whether it may be written as a confirmed
standalone sale.

Rules, in priority order:
  * No explicit sold evidence -> uncertain. A listing vanishing is not a sale.
  * Additional coins/items in the title -> bundle, excluded from standalone value.
  * Privy-mark carded coin -> privy, a different product.
  * Carded/coin-in-card, proof, silver, folder, tube, insert or multi-coin
    packaging -> other_configuration, held for review.
  * Only one Sleepytime PNC with no extra configuration -> standalone.
  * Best Offer wording without a disclosed accepted amount -> the displayed
    amount is quarantined and never becomes a confirmed sale price.

No network, no database, no publication. The script emits JSON plus a short
human summary; the test entry point imports replay().
"""
import argparse
import json
import re
from pathlib import Path

DEFAULT_FIXTURE = (Path(__file__).resolve().parent.parent
                   / "fixtures" / "sleepytime_sold_2026-11-28.json")

CLASSES = ("standalone", "bundle", "other_configuration", "privy", "uncertain")

_BUNDLE_PATTERNS = (
    (r"\b(?:bundle|job\s+lot|lot\s+of|bulk)\b", "bundle wording"),
    (r"\b(?:plus|with|and)\s+\d+\s+(?:extra\s+|till\s+)?coins?\b", "extra coins named"),
    (r"\+\s*\d+\s+(?:extra\s+|till\s+)?coins?\b", "extra coins named"),
    (r"\b\d+\s+(?:extra\s+)?till\s+coins?\b", "extra till coins named"),
    (r"\bset\s+of\s+\d+\b", "multi-item set"),
)

_PRIVY_PATTERNS = (
    (r"\bprivy\s*mark\b", "privy mark"),
    (r"\bprivymark\b", "privy mark"),
    (r"\bprivy\b", "privy mark"),
)

_OTHER_CONFIG_PATTERNS = (
    (r"\bcoin[\s-]*in[\s-]*card\b", "coin in card, not a cover"),
    (r"\bin[\s-]*card\b", "carded coin"),
    (r"\bcarded\b", "carded coin"),
    (r"\bcoincard\b", "carded coin"),
    (r"\buncirculated\b", "uncirculated coin, not the PNC"),
    (r"\bproof\b", "proof coin"),
    (r"\bsilver\b", "silver coin"),
    (r"\bminisheet\b", "minisheet product"),
    (r"\bfolder\b", "folder product"),
    (r"\btube\b", "tube product"),
    (r"\binsert\b", "insert product"),
    (r"\bstamp\s+(?:pack|pin)\b", "stamp/pin cover"),
    (r"\bpin\s+cover\b", "pin cover"),
    (r"(?<![\$\d])(?:two|three|four|five|[2-9])\s*[- ]?coin\b",
     "multi-coin product"),
)


def load_observations(path=None):
    """Return the fixture's observation list, refusing malformed input."""
    path = Path(path or DEFAULT_FIXTURE)
    with open(path, "r", encoding="utf-8") as stream:
        data = json.load(stream)
    observations = data.get("observations")
    if not isinstance(observations, list):
        raise ValueError(f"{path} has no observations list")
    return data, observations


def dedupe(observations):
    """Keep the first observation per marketplace item ID.

    Returns (unique, duplicate_ids). Observations without an item ID are kept
    as distinct uncertain rows rather than being merged.
    """
    seen = set()
    unique = []
    duplicates = []
    for observation in observations:
        item_id = str(observation.get("item_id") or "").strip()
        if item_id and item_id in seen:
            duplicates.append(item_id)
            continue
        if item_id:
            seen.add(item_id)
        unique.append(observation)
    return unique, duplicates


def _match(patterns, title):
    for pattern, label in patterns:
        if re.search(pattern, title):
            return label
    return None


def classify(observation):
    """Classify one observation. Returns (class, [reasons])."""
    title = str(observation.get("title") or "").lower()
    evidence = observation.get("sold_evidence") or {}
    if not evidence.get("explicit"):
        return "uncertain", [
            "no explicit sold evidence; a listing disappearing is not a sale"
        ]

    bundle = _match(_BUNDLE_PATTERNS, title)
    if bundle:
        return "bundle", [f"{bundle}: more than one standalone PNC in the sale"]

    privy = _match(_PRIVY_PATTERNS, title)
    if privy:
        return "privy", [f"{privy}: different product from the standalone PNC"]

    other = _match(_OTHER_CONFIG_PATTERNS, title)
    if other:
        return "other_configuration", [
            f"{other}: product configuration does not match the PNC"
        ]

    return "standalone", [
        "title matches one Sleepytime PNC with no extra coins or packaging"
    ]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value <= 0:  # NaN or non-positive
        return None
    return round(float(value), 2)


def review(observation):
    """Build the per-item decision used by the replay report."""
    item_id = str(observation.get("item_id") or "").strip()
    item_class, reasons = classify(observation)
    best = observation.get("best_offer") or {}
    item_price = _number(observation.get("item_price_aud"))
    postage = observation.get("postage_aud")
    postage = 0.0 if postage == 0 else _number(postage)
    delivered = (round(item_price + postage, 2)
                 if item_price is not None and postage is not None else None)

    quarantined = (
        bool(best.get("wording_present"))
        and bool(best.get("accepted_wording", best.get("wording_present")))
        and not bool(best.get("accepted_amount_disclosed")))
    quarantine_reason = None
    if quarantined:
        quarantine_reason = (
            "Best Offer accepted wording present and the accepted amount is not "
            "disclosed; the displayed amount is quarantined and is not a confirmed "
            "sale price"
        )

    currency = str(observation.get("currency") or "").upper()
    price_usable = item_price is not None and currency in {"AUD", "AU", "A$"}
    confirmed = (item_class == "standalone" and price_usable
                 and not quarantined)

    if item_class == "bundle":
        reasons.append("excluded from standalone valuation")
    elif item_class == "other_configuration":
        reasons.append("held for review; not valued as the standalone PNC")
    elif item_class == "standalone" and quarantined:
        reasons.append("no confirmed sale price")
    elif confirmed:
        reasons.append("written as a confirmed sale")
    if observation.get("presale"):
        reasons.append("presale flagged")
    if observation.get("link_verified") is False:
        reasons.append("link unverified")

    return {
        "item_id": item_id,
        "sold_date": observation.get("sold_date"),
        "title": observation.get("title"),
        "class": item_class,
        "presale": bool(observation.get("presale")),
        "link_verified": observation.get("link_verified"),
        "buying_format": observation.get("buying_format"),
        "disclosed_item_price_aud": item_price,
        "disclosed_postage_aud": postage,
        "delivered_total_aud": delivered,
        "best_offer": {
            "wording_present": bool(best.get("wording_present")),
            "accepted_wording": bool(best.get("accepted_wording")),
            "accepted_amount_disclosed": bool(best.get("accepted_amount_disclosed")),
        },
        "price_quarantined": quarantined,
        "quarantine_reason": quarantine_reason,
        "confirmed_sale": confirmed,
        "write": {
            "confirmed_sale": confirmed,
            "price_aud": item_price if confirmed else None,
            "postage_aud": postage if confirmed else None,
        },
        "reasons": reasons,
    }


def replay(observations, product=None):
    """Replay observations and return a machine-readable report."""
    unique, duplicates = dedupe(observations)
    items = [review(observation) for observation in unique]
    counts = {name: 0 for name in CLASSES}
    for item in items:
        counts[item["class"]] += 1
    confirmed = [item for item in items if item["confirmed_sale"]]
    report = {
        "product": product or {},
        "inputs": {
            "observations_in": len(observations),
            "distinct_item_ids": len(unique),
            "duplicates_removed": len(duplicates),
            "duplicate_item_ids": duplicates,
        },
        "counts": {
            **counts,
            "bundle_excluded": counts["bundle"],
            "other_configuration_held": counts["other_configuration"],
            "price_quarantined": sum(
                1 for item in items if item["price_quarantined"]),
            "presales_flagged": sum(1 for item in items if item["presale"]),
            "confirmed_sale_rows": len(confirmed),
            "prices_inferred": 0,
        },
        "confirmed_sale_item_ids": [item["item_id"] for item in confirmed],
        "items": items,
    }
    return report


def summary_lines(report):
    """Short human summary: one line per item plus totals."""
    lines = []
    inputs = report["inputs"]
    lines.append(
        "Sleepytime PNC sold replay: {observations_in} observations, "
        "{distinct_item_ids} distinct item IDs, {duplicates_removed} duplicates".format(
            **inputs))
    lines.append("")
    header = "{:<14} {:<11} {:<20} {:<9} {:<12} {}".format(
        "ITEM", "SOLD", "CLASS", "CONFIRMED", "PRICE", "WHY")
    lines.append(header)
    lines.append("-" * len(header))
    for item in report["items"]:
        price = item["disclosed_item_price_aud"]
        price_text = "A${:.2f}".format(price) if price is not None else "-"
        if item["disclosed_postage_aud"] is not None and price is not None:
            price_text += "+{:.2f}".format(item["disclosed_postage_aud"])
        if item["price_quarantined"]:
            price_text += " (quarantined)"
        lines.append("{:<14} {:<11} {:<20} {:<9} {:<12} {}".format(
            item["item_id"] or "-",
            item["sold_date"] or "-",
            item["class"],
            "yes" if item["confirmed_sale"] else "no",
            price_text,
            "; ".join(item["reasons"])))
    counts = report["counts"]
    lines.append("")
    lines.append(
        "Totals: confirmed={confirmed_sale_rows} quarantined={price_quarantined} "
        "bundle={bundle} other={other_configuration} privy={privy} "
        "uncertain={uncertain} presales={presales_flagged} inferred={prices_inferred}".format(
            **counts))
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", nargs="?", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--json", dest="json_path",
                        help="write the machine-readable report to this path")
    parser.add_argument("--quiet", action="store_true",
                        help="do not print the human summary")
    args = parser.parse_args(argv)

    fixture, observations = load_observations(args.fixture)
    report = replay(observations, product=fixture.get("product"))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
        print("json: {}".format(args.json_path))
    if not args.quiet:
        print("\n".join(summary_lines(report)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
