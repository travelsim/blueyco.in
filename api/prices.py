import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, wait
from html.parser import HTMLParser

# ── CONFIG ───────────────────────────────────────────────────────────────────
RAPIDAPI_KEY = os.environ.get('RAPIDAPI_KEY', '')
RAPIDAPI_HOST = 'ebay-average-selling-price.p.rapidapi.com'
RAPIDAPI_URL = f'https://{RAPIDAPI_HOST}/findCompletedItems'

EBAY_LIVE_HOST = 'real-time-ebay.p.rapidapi.com'
EBAY_LIVE_URL = f'https://{EBAY_LIVE_HOST}/search'

# Simple in-memory cache (persists for the lifetime of the serverless instance)
_cache = {}
_last_fetch = {}

# The function has a 10s maxDuration (Hobby). Every upstream request gets a
# short timeout, coins are fetched concurrently, and whatever has not finished
# by the deadline is returned as a partial snapshot instead of timing out.
UPSTREAM_TIMEOUT = 5
FETCH_DEADLINE = 7.5
MAX_WORKERS = 20
CACHE_TTL = 6 * 3600         # full snapshot
PARTIAL_CACHE_TTL = 5 * 60   # partial snapshot: retry soon

# ── HELPER FUNCTIONS (extracted and cleaned from server.py) ──────────────────

def _http_get(url, accept='text/html', timeout=UPSTREAM_TIMEOUT):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': accept,
        'Accept-Language': 'en-AU,en;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')

def _parse_price(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    has_decimal = '.' in s
    cleaned = re.sub(r'[^\d.]', '', s)
    if not cleaned:
        return None
    try:
        val = float(cleaned)
    except ValueError:
        return None
    if not has_decimal and val > 200:
        val = val / 100
    return round(val, 2) if val > 0 else None

class _LDParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._on = False
        self._buf = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and ('type', 'application/ld+json') in attrs:
            self._on, self._buf = True, []

    def handle_endtag(self, tag):
        if tag == 'script' and self._on:
            self._on = False
            self.blocks.append(''.join(self._buf))

    def handle_data(self, data):
        if self._on:
            self._buf.append(data)

def _ld_products(html, base):
    p = _LDParser()
    p.feed(html)
    results = []
    for block in p.blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        nodes = []
        if isinstance(data, list):
            nodes = data
        elif isinstance(data, dict):
            t = data.get('@type', '')
            if t == 'ItemList':
                nodes = [i.get('item', i) for i in data.get('itemListElement', [])]
            elif t == 'Product':
                nodes = [data]
        for n in nodes:
            if not isinstance(n, dict):
                continue
            t = n.get('@type', '')
            if isinstance(t, list):
                t = t[0] if t else ''
            if t not in ('Product', 'product'):
                continue
            offers = n.get('offers', {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = _parse_price(offers.get('price'))
            if price:
                results.append({
                    'price': price,
                    'name': n.get('name', ''),
                    'url': n.get('url', '')
                })
    return results

def _scrape_coinxchange(search_term):
    """Recently-sold CoinXchange prices. Delegates to server.py's parser (the
    same one /api/buy-options uses), which reads the rendered listing grid;
    CoinXchange no longer ships JSON-LD, so the generic fallback below finds
    nothing on its own."""
    try:
        legacy = _legacy()
        if legacy is not None:
            return legacy._scrape_coinxchange(search_term, sold_only=True)
    except Exception as e:
        print(f"CoinXchange legacy scraper error ({search_term}): {e}")
    return _scrape_coinxchange_generic(search_term)


def _legacy():
    here = os.path.dirname(os.path.abspath(__file__))
    for root in (os.path.dirname(here), here):
        if os.path.exists(os.path.join(root, 'server.py')):
            if root not in sys.path:
                sys.path.insert(0, root)
            import server
            return server
    return None


def _scrape_coinxchange_generic(search_term):
    q = urllib.parse.quote(search_term)
    url = f'https://www.coinxchange.com.au/buy?search={q}'
    try:
        html = _http_get(url)
    except Exception:
        return []

    listings = []

    # Strategy 1 — JSON-LD
    for prod in _ld_products(html, 'https://www.coinxchange.com.au'):
        if prod.get('price'):
            listings.append({'price': prod['price'], 'title': prod.get('name', ''), 'url': prod.get('url') or url})

    # Strategy 2 — embedded JSON
    if not listings:
        for m in re.finditer(r'\{[^{}]{0,400}"price"[^{}]{0,400}\}', html):
            try:
                obj = json.loads(m.group())
                p = _parse_price(obj.get('price') or obj.get('Price'))
                if p and 5 < p < 10000:
                    listings.append({'price': p, 'title': str(obj.get('title') or obj.get('name') or ''), 'url': obj.get('url') or url})
            except Exception:
                continue

    # Dedup
    unique = []
    seen = set()
    for l in sorted(listings, key=lambda x: x['price']):
        key = round(l['price'], 0)
        if key not in seen:
            seen.add(key)
            unique.append(l)
    return unique[:15]

def _summarise(listings):
    """Summarise CoinXchange listings for /api/prices.

    Keep both the dynamic server naming (count/listings) and the broader
    /api/prices naming (total_results/products) so frontend consumers can use
    either shape without breaking if this serverless fallback is enabled.
    """
    prices = [l['price'] for l in listings if l.get('price')]
    if not prices:
        return None
    top_listings = listings[:10]
    return {
        'average_price': round(sum(prices) / len(prices), 2),
        'min_price': min(prices),
        'max_price': max(prices),
        'count': len(prices),
        'listings': top_listings,
        'total_results': len(prices),
        'products': top_listings,
    }

def _fetch_ebay(coin):
    if not RAPIDAPI_KEY:
        return {"products": [], "average_price": None}

    payload = json.dumps({
        'keywords': coin['ebay_kw'],
        'max_search_results': '60',
        'site_id': '15',
        'remove_outliers': 'true',
    }).encode()

    req = urllib.request.Request(
        RAPIDAPI_URL,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'x-rapidapi-host': RAPIDAPI_HOST,
            'x-rapidapi-key': RAPIDAPI_KEY,
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT) as r:
            data = json.loads(r.read())
            return {
                "products": data.get("products", [])[:20],
                "average_price": data.get("average_price"),
                "total_results": data.get("total_results", 0),
            }
    except Exception as e:
        print(f"eBay fetch error for {coin['id']}: {e}")
        return {"products": [], "average_price": None, "error": str(e)}

# ── COIN CATALOGUE (embedded for serverless) ─────────────────────────────────
COINS = [
    {'id': 's1_bluey', 'ebay_kw': '2024 $1 Bluey Dollarbuck Bluey coin uncirculated', 'search': '2024 Bluey Dollarbuck Bluey'},
    {'id': 's1_bingo', 'ebay_kw': '2024 $1 Bluey Dollarbuck Bingo coin uncirculated', 'search': '2024 Bluey Dollarbuck Bingo'},
    {'id': 's1_bandit', 'ebay_kw': '2024 $1 Bluey Dollarbuck Bandit coin uncirculated', 'search': '2024 Bluey Dollarbuck Bandit'},
    {'id': 's1_chilli', 'ebay_kw': '2024 $1 Bluey Dollarbuck Chilli coin uncirculated', 'search': '2024 Bluey Dollarbuck Chilli'},
    {'id': 's1_muffin', 'ebay_kw': '2024 $1 Bluey Dollarbuck Muffin coin uncirculated', 'search': '2024 Bluey Dollarbuck Muffin'},
    {'id': 's1_socks', 'ebay_kw': '2024 $1 Bluey Dollarbuck Socks coin uncirculated', 'search': '2024 Bluey Dollarbuck Socks'},
    {'id': 's1_nana', 'ebay_kw': '2024 $1 Bluey Dollarbuck Nana coin uncirculated', 'search': '2024 Bluey Dollarbuck Nana'},
    {'id': 's1_bob_bilby', 'ebay_kw': '2024 $1 Bluey Dollarbuck Bob Bilby coin uncirculated', 'search': '2024 Bluey Dollarbuck Bob Bilby'},
    {'id': 's1_lucky', 'ebay_kw': '2024 $1 Bluey Dollarbuck Lucky coin uncirculated', 'search': '2024 Bluey Dollarbuck Lucky'},
    {'id': 's1_rusty', 'ebay_kw': '2024 $1 Bluey Dollarbuck Rusty coin uncirculated', 'search': '2024 Bluey Dollarbuck Rusty'},
    {'id': 's1_10_coin_folder_set', 'ebay_kw': '2024 $1 Bluey 10 coin tube folder set', 'search': '2024 Bluey 10 coin tube folder set'},
    {'id': 's1_coloured_insert_variant', 'ebay_kw': '2024 Bluey Coloured Insert Variant coin', 'search': '2024 Bluey insert variant'},
    {'id': 's2_xmas_unc', 'ebay_kw': '2025 $1 Bluey Christmas coloured uncirculated coin', 'search': '2025 Bluey Christmas uncirculated'},
    {'id': 's2_xmas_silv', 'ebay_kw': '2025 $1 Bluey Christmas silver proof coin', 'search': '2025 Bluey Christmas silver proof'},
    {'id': 's3_rain', 'ebay_kw': '2026 $2 Bluey Rain privy mark uncirculated coin', 'search': '2026 Bluey Rain privy mark'},
    {'id': 's3_sleepytime', 'ebay_kw': '2026 $2 Bluey Sleepytime privy mark uncirculated', 'search': '2026 Bluey Sleepytime privy mark'},
    {'id': 's3_camping', 'ebay_kw': '2026 $2 Bluey Camping privy mark uncirculated coin', 'search': '2026 Bluey Camping privy mark'},
    {'id': 's3_babyrace', 'ebay_kw': '2026 $2 Bluey Baby Race privy mark uncirculated', 'search': '2026 Bluey Baby Race privy mark'},
    {'id': 's3_granny', 'ebay_kw': '2026 $2 Bluey Granny Mobile privy mark uncirculated', 'search': '2026 Bluey Granny Mobile privy mark'},
    {'id': 's3_rain_privy', 'ebay_kw': '2026 $2 Bluey Rain Privy Mark coin', 'search': '2026 Bluey Rain Privy Mark'},
    {'id': 's3_sleepytime_privy', 'ebay_kw': '2026 $2 Bluey Sleepytime Privy Mark coin', 'search': '2026 Bluey Sleepytime Privy Mark'},
    {'id': 's3_camping_privy', 'ebay_kw': '2026 $2 Bluey Camping Privy Mark coin', 'search': '2026 Bluey Camping Privy Mark'},
    {'id': 's3_babyrace_privy', 'ebay_kw': '2026 $2 Bluey Baby Race Privy Mark coin', 'search': '2026 Bluey Baby Race Privy Mark'},
    {'id': 's3_granny_privy', 'ebay_kw': '2026 $2 Bluey Granny Mobile Privy Mark coin', 'search': '2026 Bluey Granny Mobile Privy Mark'},
    {'id': 's3_heeler_family_privy', 'ebay_kw': '2026 $2 Bluey Heeler Family Privy Mark coin', 'search': '2026 Bluey Heeler Family Privy Mark'},
    {'id': 's3_proof_ab', 'ebay_kw': '2026 $2 Bluey coloured proof aluminium bronze coin', 'search': '2026 Bluey proof aluminium bronze'},
    {'id': 's3_proof_silv', 'ebay_kw': '2026 $2 Bluey coloured silver proof coin', 'search': '2026 Bluey silver proof'},
    {'id': 's3_proof_silv_uncoloured', 'ebay_kw': '2026 $2 Bluey silver proof uncoloured coin', 'search': '2026 Bluey silver proof uncoloured'},
    {'id': 's3_sleepytime_insert', 'ebay_kw': '2026 $2 Bluey Sleepytime Coloured Insert coin', 'search': '2026 Bluey Sleepytime insert'},
    {'id': 's3_till_bluey', 'ebay_kw': '2026 $2 Bluey coloured till coin circulation', 'search': '2026 Bluey till coin'},
    {'id': 's3_till_bingo', 'ebay_kw': '2026 $2 Bingo coloured till coin circulation', 'search': '2026 Bingo till coin'},
    {'id': 's3_pnc_bluey', 'ebay_kw': '2026 $2 Bluey For Real Life PNC AusPost', 'search': '2026 Bluey For Real Life PNC'},
    {'id': 's3_pnc_bingo', 'ebay_kw': '2026 $2 Bingo Hooray PNC AusPost', 'search': '2026 Bingo Hooray PNC'},
    {'id': 's3_pnc_bandit', 'ebay_kw': '2026 $2 Bluey Bandit PNC', 'search': '2026 Bandit PNC'},
    {'id': 's3_pnc_chilli', 'ebay_kw': '2026 $2 Bluey Chilli PNC', 'search': '2026 Chilli PNC'},
    {'id': 's3_pin_bluey', 'ebay_kw': 'Bluey Pin Cover 2026', 'search': 'Bluey Pin Cover'},
    {'id': 's3_pin_bingo', 'ebay_kw': 'Bingo Pin Cover 2026', 'search': 'Bingo Pin Cover'},
    {'id': 's3_pin_bandit', 'ebay_kw': 'Bandit Pin Cover 2026', 'search': 'Bandit Pin Cover'},
    {'id': 's3_pin_chilli', 'ebay_kw': 'Chilli Pin Cover 2026', 'search': 'Chilli Pin Cover'},
    {'id': 's3_pin_muffin', 'ebay_kw': 'Muffin Pin Cover 2026', 'search': 'Muffin Pin Cover'},
    # Series 4 — 2027 Cricket episode collectible coins (RAM launch prices).
    {'id': 's4_cricket_unc', 'ebay_kw': '2027 $1 Bluey Cricket Rusty coloured uncirculated coin card', 'search': '2027 Bluey Cricket $1 uncirculated'},
    {'id': 's4_cricket_proof', 'ebay_kw': '2027 $1 Bluey Cricket silver proof coin cricket ball tin', 'search': '2027 Bluey Cricket $1 silver proof'},
    # Series 1 tube sets — these ship in the frontend catalogue and in
    # server.py; they were missing here so they never received live prices.
    {'id': 's1_mumdad', 'ebay_kw': '2024 $1 Bluey Mum & Dad Dollarbuck tube set unc', 'search': '2024 Bluey Mum and Dad tube set'},
    {'id': 's1_muffinsocks', 'ebay_kw': '2024 $1 Bluey Muffin & Socks Dollarbuck tube set unc', 'search': '2024 Bluey Muffin Socks tube set'},
    {'id': 's1_radfrisky', 'ebay_kw': '2024 $1 Bluey Rad & Frisky Dollarbuck tube set unc', 'search': '2024 Bluey Rad Frisky tube set'},
    {'id': 's1_stripetrixie', 'ebay_kw': '2024 $1 Bluey Stripe Trixie Nana Dollarbuck tube set unc', 'search': '2024 Bluey Stripe Trixie tube set'},
    {'id': 's1_blueyfriends', 'ebay_kw': '2024 $1 Bluey Bluey & Friends Dollarbuck tube set unc', 'search': '2024 Bluey friends tube set'},
    {'id': 's1_bingofriends', 'ebay_kw': '2024 $1 Bluey Bingo & Friends Dollarbuck tube set unc', 'search': '2024 Bluey Bingo friends tube set'},
]

# ── MAIN HANDLER (Vercel Python runtime, current format) ────────────────────
# Vercel's current Python serverless runtime requires a class-based handler
# that inherits from BaseHTTPRequestHandler, NOT a v1-style `def handler(request)`.
# See: https://vercel.com/docs/functions/serverless-functions/runtimes/python
from http.server import BaseHTTPRequestHandler

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._respond()

    def do_POST(self):
        self._respond()

    def _respond(self):
        try:
            payload, complete = _build_payload()
        except Exception as e:
            # Surface the error so it's visible in Vercel logs
            print(f"handler error: {e}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode())
            return

        max_age = CACHE_TTL if complete else PARTIAL_CACHE_TTL
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', f's-maxage={max_age}, stale-while-revalidate')
        self.send_header('X-Prices-Complete', 'true' if complete else 'false')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())


def _load_base_cache():
    for candidate in ('ebay_cache.json', '/var/task/ebay_cache.json', os.path.join(os.path.dirname(__file__), '..', 'ebay_cache.json')):
        try:
            with open(candidate, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def _load_manual():
    # Vercel deploys from the project root, but the working directory at
    # function runtime is the project root too — try both paths.
    for candidate in ('retailer_prices.json', '/var/task/retailer_prices.json', os.path.join(os.path.dirname(__file__), '..', 'retailer_prices.json')):
        try:
            with open(candidate, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def _fetch_coin(coin):
    cid = coin['id']

    # eBay data (only if key is present)
    ebay_data = None
    if RAPIDAPI_KEY:
        try:
            ebay_data = _fetch_ebay(coin)
        except Exception as e:
            print(f"eBay error for {cid}: {e}")

    # CoinXchange scrape (best effort)
    cx_data = None
    try:
        listings = _scrape_coinxchange(coin['search'])
        cx_data = _summarise(listings) or {}
        cx_data['search_url'] = 'https://www.coinxchange.com.au/buy?search=' + urllib.parse.quote(coin['search'])
    except Exception as e:
        print(f"CoinXchange error for {cid}: {e}")

    return {'ebay': ebay_data, 'coinxchange': cx_data}


def _build_payload(coins=None, fetch_coin=None, deadline=None):
    """Return (snapshot, complete). Coins still in flight at the deadline get
    cached baseline or manual prices, and the partial snapshot is cached briefly."""
    coins = COINS if coins is None else coins
    fetch_coin = fetch_coin or _fetch_coin
    deadline = FETCH_DEADLINE if deadline is None else deadline
    now = time.time()

    # Return cached snapshot if still fresh
    if 'full' in _cache and now < _last_fetch.get('full', 0):
        return _cache['full'], _cache.get('complete', True)

    base_cache = _load_base_cache()
    manual = _load_manual()
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    futures = {pool.submit(fetch_coin, coin): coin['id'] for coin in coins}
    done, pending = wait(futures, timeout=deadline)
    # Don't block on stragglers; their sockets time out on their own.
    pool.shutdown(wait=False, cancel_futures=True)

    snapshot = {}
    for future, cid in futures.items():
        cached = base_cache.get(cid, {})
        result = {'ebay': cached.get('ebay'), 'coinxchange': cached.get('coinxchange')}
        if future in done:
            try:
                fetched = future.result()
                if isinstance(fetched, dict):
                    if fetched.get('ebay') is not None:
                        result['ebay'] = fetched['ebay']
                    if fetched.get('coinxchange') is not None:
                        result['coinxchange'] = fetched['coinxchange']
            except Exception as e:
                print(f"fetch error for {cid}: {e}")
        result['manual'] = manual.get(cid)
        snapshot[cid] = result

    complete = not pending
    if pending:
        print(f"prices: {len(pending)}/{len(coins)} coins unfinished at {deadline}s deadline")

    # Save to in-memory cache (stores expiry time)
    _cache['full'] = snapshot
    _cache['complete'] = complete
    _last_fetch['full'] = now + (CACHE_TTL if complete else PARTIAL_CACHE_TTL)
    return snapshot, complete
