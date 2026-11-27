import json
import os
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, wait
from http.server import BaseHTTPRequestHandler

# The legacy `server.py` holds the retailer catalogue, EPN affiliate wrapping and
# the per-retailer scrapers. Importing it keeps a single source of truth instead
# of duplicating ~500 lines of scraping logic into the serverless function.
def _repo_root():
    """Walk up from this file until server.py is found (works locally, on
    Vercel, and when the module is loaded by absolute spec)."""
    here = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.exists(os.path.join(here, 'server.py')):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        here = parent


_ROOT = _repo_root()
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import server as legacy  # noqa: E402

# The function runs with a 10s maxDuration (Hobby). Every retailer scrape runs
# concurrently and whatever has not returned by the deadline is replaced with a
# link-only option (or its manual price override), so the panel always responds
# inside budget with useful links.
DEADLINE = 7.0
MAX_WORKERS = 6
# Asking prices move and new listings appear, so the panel is rebuilt every
# half hour rather than serving a day-old list.
CACHE_TTL = 30 * 60
MAX_BODY_BYTES = 4096

_cache = {}

# Audit 2026-11-13: eBay listings that belong to a different product (or cannot
# be tied to one). Keyed by coin id, value is the eBay item ids to drop.
EXCLUDED_EBAY_ITEMS = {
    's1_card_bingo': {'296857674494'},
    's1_10_coin_folder_opened': {'147300593732'},
    's3_folder_opened': {'147300593732'},
    's1_pnc_bluey': {'297694790286'},
    's1_card_bluey': {'178152522378'},
    's3_granny': {'198351768831'},
    's3_granny_privy': {'198351768831'},
    's3_sleepytime': {'198351768831'},
    's3_sleepytime_privy': {'198351768831'},
    's3_pin_babyrace': {'206286072326'},
    's3_pin_camping': {'206286072326'},
}

# Audit 2026-11-13: privy twins with identical search keywords show the same
# listings, so they are served from the primary product's panel.
MERGED_INTO = {
    's3_babyrace_privy': 's3_babyrace',
    's3_camping_privy': 's3_camping',
    's3_granny_privy': 's3_granny',
    's3_rain_privy': 's3_rain',
    's3_sleepytime_privy': 's3_sleepytime',
    # 2026 Impressions coins were renamed to their AusPost product numbers; old ids still resolve.
    's3_impressions_pnc_sleepytime': '76604949',
    's3_impressions_heelers_proof_pnc': '76604950',
    's3_impressions_heelers_silver_pnc': '76604951',
    's3_impressions_pnc_bluey_1_2': '76604956',
    's3_impressions_2coin_minisheet_boxed5': '76604957',
    's3_impressions_heelers_proof_2coin_minisheet': '76604958',
    's3_impressions_pnc_3coin': '76604959',
    's3_impressions_pnc_bingo_1_2': '76605600',
}


def _excluded(coin_id, option):
    banned = EXCLUDED_EBAY_ITEMS.get(coin_id)
    if not banned:
        return False
    match = re.search(r'/itm/(\d+)', option.get('url') or '')
    return bool(match and match.group(1) in banned)


def _manual():
    """Manual retailer price overrides, tolerating the serverless cwd."""
    for candidate in (
        'retailer_prices.json',
        '/var/task/retailer_prices.json',
        os.path.join(_ROOT, 'retailer_prices.json'),
    ):
        try:
            with open(candidate, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def _fallback(retailer, keywords, coin_id, manual):
    """Manual override if present, otherwise a plain search link.

    eBay URLs are routed through the shared EPN affiliate wrapper (a
    no-op for other retailers, and for eBay when no campaign is
    configured), so buy-options links never ship untagged.
    """
    entry = (manual.get(coin_id) or {}).get(retailer['id'])
    # eBay links are generated from the coin's tightened query; old hand-written
    # eBay search URLs were loose (some pointed at sold pages), so eBay manual
    # entries are honoured only when they pin a verified live item URL.
    ebay_item = retailer.get('id') == 'ebay' and bool(
        entry and re.search(r'/itm/\d+', entry.get('url') or ''))
    if entry and (retailer.get('id') != 'ebay' or ebay_item):
        q = urllib.parse.quote(keywords)
        checked_at = entry.get('checkedAt')
        try:
            checked_at = float(checked_at)
        except (TypeError, ValueError):
            checked_at = 0
        age = time.time() - checked_at
        fresh_manual_price = checked_at > 0 and 0 <= age <= 7 * 24 * 3600
        price = entry.get('price') if fresh_manual_price else None
        postage = entry.get('postage') if price is not None else None
        try:
            postage = float(postage) if postage is not None else None
        except (TypeError, ValueError):
            postage = None
        return [{
            'retailer_id': retailer['id'],
            'name': retailer['name'],
            'price': price,
            'postage': postage,
            'available': entry.get('available', True) if price is not None else None,
            'price_type': 'asking' if price is not None else None,
            'checkedAt': checked_at if price is not None else None,
            'subtitle': entry.get('subtitle') if price is not None else None,
            'url': legacy.affiliate_url(
                entry.get('url') or retailer['search_url'].replace('{q}', q),
                coin_id=coin_id, source='ebay_search'),
            'link_only': price is None,
        }]
    return legacy._link_only_option(retailer, keywords, coin_id=coin_id)


def _scrape(retailer, keywords, coin_id):
    try:
        kind = retailer.get('type')
        if kind == 'shopify':
            return legacy._shopify_options(retailer, keywords)
        if kind == 'jsonld':
            return legacy._jsonld_options(retailer, keywords)
        if kind == 'coinxchange':
            return legacy._coinxchange_buy_options(retailer, keywords, coin_id=coin_id)
        if kind == 'ebay_live':
            return legacy._ebay_live_options(retailer, keywords, coin_id=coin_id)
        if kind == 'cashconverters':
            return legacy._cashconverters_options(retailer, keywords)
        return []
    except Exception as e:
        print(f"buy-options scrape fail [{retailer.get('id')}]: {e}")
        return []


def get_buy_options(coin_id, keywords, tracking=False):
    if tracking:
        retailer = next((r for r in legacy.RETAILERS if r.get('id') == 'ebay'), None)
        if retailer is None:
            return [], False
        return legacy._ebay_live_tracking_options(retailer, keywords, coin_id)

    now = time.time()
    hit = _cache.get(coin_id)
    if hit and now - hit['fetchedAt'] < CACHE_TTL:
        return hit['options'], True

    manual = _manual()
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    retailers = list(legacy.RETAILERS)
    futures = {pool.submit(_scrape, r, keywords, coin_id): r for r in retailers}
    done, pending = wait(futures, timeout=DEADLINE)
    pool.shutdown(wait=False, cancel_futures=True)

    options = []
    complete = not pending
    for future, retailer in futures.items():
        results = []
        if future in done:
            try:
                results = future.result() or []
            except Exception as e:
                print(f"buy-options error [{retailer['id']}]: {e}")
        manual_entry = (manual.get(coin_id) or {}).get(retailer['id']) or {}
        # A verified live eBay item URL replaces a generic link-only result;
        # useAsLinkOnly does the same for a coin-specific search URL.
        manual_item = retailer.get('id') == 'ebay' and bool(
            re.search(r'/itm/\d+', manual_entry.get('url') or ''))
        if (results and all(option.get('link_only') or option.get('price') is None for option in results)
                and (manual_item or manual_entry.get('useAsLinkOnly') is True)):
            results = _fallback(retailer, keywords, coin_id, manual)
        if not results:
            # Unfinished or failed scrape still yields an actionable link.
            options.extend(_fallback(retailer, keywords, coin_id, manual))
            continue
        for option in results:
            if option.get('price') is not None:
                option.setdefault('price_type', 'asking')
        options.extend(results)

    priced = sorted(
        legacy._dedupe_listings([o for o in options if not o.get('link_only') and o.get('price') is not None]),
        key=legacy._buy_total_sort_key,
    )
    link_only = [o for o in options if o.get('link_only') or o.get('price') is None]

    priced = [o for o in priced if not _excluded(coin_id, o)]
    link_only = [o for o in link_only if not _excluded(coin_id, o)]
    final = priced[:10] + link_only
    # Blend the independent, expiring current-offer projection into the live
    # panel. It is separate from the historical sales ledger.
    if os.environ.get('DATABASE_URL') and not tracking:
        try:
            from api import active_offers
            with active_offers.connect() as conn:
                stored = active_offers.current_offers(conn, coin_id, 'ebay')
            for lid, title, price, postage, url, source in stored:
                option = {'retailer_id': 'ebay', 'name': 'eBay', 'title': title,
                          'price': float(price), 'postage': float(postage) if postage is not None else None,
                          'available': True, 'price_type': 'asking', 'url': url,
                          'link_only': False}
                if not _excluded(coin_id, option) and not any(
                        re.search(r'/itm/(\d+)', o.get('url') or '') and
                        re.search(r'/itm/(\d+)', o.get('url') or '').group(1) == str(lid)
                        for o in final):
                    final.insert(0, option)
        except Exception as exc:
            print(f"active offer read unavailable: {type(exc).__name__}")
    if complete:
        _cache[coin_id] = {'options': final, 'fetchedAt': now}
    return final, complete


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            self._json(413, {'error': 'Request body too large.'})
            return
        try:
            body = json.loads(self.rfile.read(length) or b'{}')
        except (json.JSONDecodeError, ValueError):
            self._json(400, {'error': 'Invalid JSON.'})
            return

        coin_id = str(body.get('coinId', ''))
        coin = legacy.COIN_BY_ID.get(coin_id)
        if not coin:
            self._json(400, {'error': 'Unknown coinId.'})
            return
        coin_id = MERGED_INTO.get(coin_id, coin_id)
        coin = legacy.COIN_BY_ID[coin_id]
        tracking = body.get('tracking') is True

        try:
            options, complete = get_buy_options(coin_id, coin['search'], tracking=tracking)
        except Exception as e:
            print(f"buy-options handler error: {e}")
            self._json(500, {'error': 'Could not load retailer prices.'})
            return

        self._json(200, {'options': options}, complete=complete, tracking=tracking)

    def do_GET(self):
        self._json(405, {'error': 'Use POST with a JSON body containing coinId.'})

    def _json(self, status, payload, complete=True, tracking=False):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Buy-Options-Complete', 'true' if complete else 'false')
        if tracking:
            self.send_header('X-Buy-Options-Mode', 'tracking-v1')
        self.end_headers()
        self.wfile.write(data)
