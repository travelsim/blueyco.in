import json
import os
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
CACHE_TTL = 6 * 3600
MAX_BODY_BYTES = 4096

_cache = {}


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
    if entry:
        q = urllib.parse.quote(keywords)
        checked_at = entry.get('checkedAt')
        try:
            checked_at = float(checked_at)
        except (TypeError, ValueError):
            checked_at = 0
        age = time.time() - checked_at
        fresh_manual_price = checked_at > 0 and 0 <= age <= 7 * 24 * 3600
        price = entry.get('price') if fresh_manual_price else None
        return [{
            'retailer_id': retailer['id'],
            'name': retailer['name'],
            'price': price,
            'available': entry.get('available', True) if price is not None else None,
            'price_type': 'asking' if price is not None else None,
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
            return legacy._coinxchange_buy_options(retailer, keywords)
        if kind == 'ebay_live':
            return legacy._ebay_live_options(retailer, keywords, coin_id=coin_id)
        if kind == 'cashconverters':
            return legacy._cashconverters_options(retailer, keywords)
        return []
    except Exception as e:
        print(f"buy-options scrape fail [{retailer.get('id')}]: {e}")
        return []


def get_buy_options(coin_id, keywords):
    now = time.time()
    hit = _cache.get(coin_id)
    if hit and now - hit['fetchedAt'] < CACHE_TTL:
        return hit['options'], True

    manual = _manual()
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    futures = {pool.submit(_scrape, r, keywords, coin_id): r for r in legacy.RETAILERS}
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
        if not results:
            # Unfinished or failed scrape still yields an actionable link.
            options.extend(_fallback(retailer, keywords, coin_id, manual))
            continue
        if len(results) > 3:
            results = sorted(results, key=lambda o: (o.get('price') is None, o.get('price') or 9999))[:3]
        for option in results:
            if option.get('price') is not None:
                option.setdefault('price_type', 'asking')
        options.extend(results)

    priced = sorted(
        [o for o in options if not o.get('link_only') and o.get('price') is not None],
        key=lambda o: o['price'],
    )
    link_only = [o for o in options if o.get('link_only') or o.get('price') is None]

    final = priced + link_only
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

        try:
            options, complete = get_buy_options(coin_id, coin['search'])
        except Exception as e:
            print(f"buy-options handler error: {e}")
            self._json(500, {'error': 'Could not load retailer prices.'})
            return

        self._json(200, {'options': options}, complete=complete)

    def do_GET(self):
        self._json(405, {'error': 'Use POST with a JSON body containing coinId.'})

    def _json(self, status, payload, complete=True):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Buy-Options-Complete', 'true' if complete else 'false')
        self.end_headers()
        self.wfile.write(data)
