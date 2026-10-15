import json
import math
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, wait

# ── CONFIG ───────────────────────────────────────────────────────────────────
RAPIDAPI_KEY = os.environ.get('RAPIDAPI_KEY', '')
RAPIDAPI_HOST = 'ebay-average-selling-price.p.rapidapi.com'
RAPIDAPI_URL = f'https://{RAPIDAPI_HOST}/findCompletedItems'


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        value = float(os.environ.get(name, default))
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


# Live refresh is opt-in. Normal Vercel requests use the committed snapshot.
RAPIDAPI_LIVE_REFRESH = _env_bool('RAPIDAPI_LIVE_REFRESH')
RAPIDAPI_REFRESH_LIMIT = min(max(_env_int('RAPIDAPI_REFRESH_LIMIT', 5), 0), 5)
RAPIDAPI_MIN_INTERVAL = max(_env_float('RAPIDAPI_MIN_INTERVAL', 1.2), 1.2)

EBAY_LIVE_HOST = 'real-time-ebay.p.rapidapi.com'
EBAY_LIVE_URL = f'https://{EBAY_LIVE_HOST}/search'

# Simple in-memory cache (persists for the lifetime of the serverless instance)
_cache = {}
_last_fetch = {}
_rapidapi_lock = threading.Lock()
_rapidapi_request_lock = threading.Lock()
_last_rapidapi_request = 0.0

# The function has a 10s maxDuration (Hobby). Normal requests use the durable
# snapshot; explicit live refreshes are bounded and serialized. The legacy
# worker settings below remain for the injected fetcher used by tests/tools.
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

def _scrape_coinxchange(search_term):
    """Fetch completed CoinXchange records through the ordinary HTML parser."""
    try:
        legacy = _legacy()
        return legacy._scrape_coinxchange(search_term, sold_only=True) if legacy else None
    except Exception as e:
        print(f"CoinXchange fetch failed: {type(e).__name__}")
        return None


def _scrape_coinxchange_all(coin):
    """Sold CoinXchange records for the catalogue query plus seller-wording variants.

    Returns None when the primary request fails (so callers keep older data);
    a failed variant is skipped. Records are de-duplicated before the strict gate.
    """
    primary = coin.get('ebay_kw') or coin.get('search') or ''
    rows = _scrape_coinxchange(primary)
    if rows is None:
        return None
    legacy = _legacy()
    variants = legacy._query_variants(coin.get('id')) if legacy else []
    rows = list(rows)
    for query in variants:
        extra = _scrape_coinxchange(query)
        if extra:
            rows += extra
    return legacy._query_dedupe(rows, ('title', 'price', 'url', 'sold_date')) if legacy else rows


def _legacy():
    here = os.path.dirname(os.path.abspath(__file__))
    for root in (os.path.dirname(here), here):
        if os.path.exists(os.path.join(root, 'server.py')):
            if root not in sys.path:
                sys.path.insert(0, root)
            import server
            return server
    return None


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

def _wait_for_rapidapi_slot(max_wait=None):
    """Reserve a request start without allowing concurrent RapidAPI calls."""
    global _last_rapidapi_request
    with _rapidapi_lock:
        now = time.monotonic()
        delay = RAPIDAPI_MIN_INTERVAL - (now - _last_rapidapi_request)
        if delay > 0:
            if max_wait is not None and delay > max_wait:
                return False
            time.sleep(delay)
        _last_rapidapi_request = time.monotonic()
        return True


def _fetch_ebay(coin, timeout=UPSTREAM_TIMEOUT, keywords=None):
    if not RAPIDAPI_KEY:
        return None

    try:
        timeout = max(0.1, float(timeout))
    except (TypeError, ValueError):
        timeout = UPSTREAM_TIMEOUT
    payload = json.dumps({
        'keywords': keywords or coin['ebay_kw'],
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
    with _rapidapi_request_lock:
        if not _wait_for_rapidapi_slot(max_wait=timeout):
            return None
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
                return _tag_ebay_urls({
                    "products": data.get("products", [])[:20],
                    "average_price": data.get("average_price"),
                    "total_results": data.get("total_results", 0),
                }, coin.get('id', ''))
        except Exception as e:
            # Keep upstream response details, URLs, and credentials out of logs.
            print(f"eBay fetch failed for {coin.get('id', 'unknown')}: {type(e).__name__}")
            return None

# ── COIN CATALOGUE (embedded for serverless) ─────────────────────────────────
COINS = [
    {'id': 's1_bluey', 'ebay_kw': '2024 $1 Bluey Dollarbuck till coin', 'search': '2024 $1 Bluey Dollarbuck till coin'},
    {'id': 's1_bingo', 'ebay_kw': '2024 $1 Bingo Dollarbuck till coin', 'search': '2024 $1 Bingo Dollarbuck till coin'},
    {'id': 's1_proof_silver', 'ebay_kw': '2024 $1 Bluey Dollarbucks fine silver coloured proof', 'search': '2024 $1 Bluey Dollarbucks fine silver coloured proof'},
    {'id': 's1_proof_coloured', 'ebay_kw': '2024 $1 Bluey Dollarbucks coloured proof coin', 'search': '2024 $1 Bluey Dollarbucks coloured proof coin'},
    {'id': 's1_10_coin_folder_set', 'ebay_kw': '2024 $1 Bluey ten coin collection folder tube set sealed unopened', 'search': '2024 $1 Bluey ten coin collection folder tube set sealed unopened'},
    {'id': 's1_10_coin_folder_opened', 'ebay_kw': '2024 $1 Bluey ten coin collection folder tube set opened', 'search': '2024 $1 Bluey ten coin collection folder tube set opened'},
    {'id': 's1_coloured_insert_variant', 'ebay_kw': '2024 $1 Bluey ten coin collection folder tube set special coloured coin', 'search': '2024 $1 Bluey ten coin collection folder tube set special coloured coin'},
    {'id': 's1_auspost_stamp_pack', 'ebay_kw': '2024 Bluey MyStamps pack 12 house shaped stamps', 'search': '2024 Bluey MyStamps pack 12 house shaped stamps'},
    {'id': 's1_impressions_pnc_colour', 'ebay_kw': '2024 Bluey limited edition coloured coin PNC', 'search': '2024 Bluey limited edition coloured coin PNC'},
    {'id': 's1_impressions_pnc_2coin', 'ebay_kw': '2024 Bluey limited edition 2 coin PNC', 'search': '2024 Bluey limited edition 2 coin PNC'},
    {'id': 's1_impressions_pnc_3coin', 'ebay_kw': '2024 Bluey limited edition 3 coin PNC envelope privy', 'search': '2024 Bluey limited edition 3 coin PNC envelope privy'},
    {'id': 's1_impressions_pnc_silver', 'ebay_kw': '2024 Bluey limited edition silver proof prestige PNC', 'search': '2024 Bluey limited edition silver proof prestige PNC'},
    {'id': 's1_coloured_bluey', 'ebay_kw': '2024 Bluey coloured uncirculated dollarbuck coin card', 'search': '2024 Bluey coloured uncirculated dollarbuck coin card'},
    {'id': 's1_coloured_heelers', 'ebay_kw': '2024 Bluey Heelers coloured uncirculated dollarbuck', 'search': '2024 Bluey Heelers coloured uncirculated dollarbuck'},
    {'id': 's1_coloured_grannies', 'ebay_kw': '2024 Bluey Grannies coloured uncirculated dollarbuck', 'search': '2024 Bluey Grannies coloured uncirculated dollarbuck'},
    {'id': 's1_three_coin_set', 'ebay_kw': '2024 Bluey Dollarbucks coloured three coin set', 'search': '2024 Bluey Dollarbucks coloured three coin set'},
    {'id': 's1_card_bluey', 'ebay_kw': '2024 Bluey $1 privy mark coin in card', 'search': '2024 Bluey $1 privy mark coin in card'},
    {'id': 's1_card_heelers', 'ebay_kw': '2024 Bluey The Heelers $1 privy mark coin card', 'search': '2024 Bluey The Heelers $1 privy mark coin card'},
    {'id': 's1_card_bingo', 'ebay_kw': '2024 Bluey Bingo $1 privy mark coin card', 'search': '2024 Bluey Bingo $1 privy mark coin card'},
    {'id': 's1_card_muffinsocks', 'ebay_kw': '2024 Bluey Muffin Socks $1 privy mark coin card', 'search': '2024 Bluey Muffin Socks $1 privy mark coin card'},
    {'id': 's1_card_stripes', 'ebay_kw': '2024 Bluey Stripe Trixie Nana $1 privy mark coin card', 'search': '2024 Bluey Stripe Trixie Nana $1 privy mark coin card'},
    {'id': 's1_card_radfrisky', 'ebay_kw': '2024 Bluey Rad Frisky $1 privy mark coin card', 'search': '2024 Bluey Rad Frisky $1 privy mark coin card'},
    {'id': 's1_card_blueyfriends', 'ebay_kw': '2024 Bluey and Friends $1 privy mark coin card', 'search': '2024 Bluey and Friends $1 privy mark coin card'},
    {'id': 's1_card_blueybingofriends', 'ebay_kw': '2024 Bluey Bingo Friends $1 privy mark coin card', 'search': '2024 Bluey Bingo Friends $1 privy mark coin card'},
    {'id': 's1_card_mumdad', 'ebay_kw': '2024 Bluey Mum Dad $1 privy mark coin card', 'search': '2024 Bluey Mum Dad $1 privy mark coin card'},
    {'id': 's1_card_grannies', 'ebay_kw': '2024 Bluey Grannies $1 privy mark coin card', 'search': '2024 Bluey Grannies $1 privy mark coin card'},
    {'id': 's1_pnc_bluey', 'ebay_kw': '2024 Bluey postal numismatic cover PNC', 'search': '2024 Bluey postal numismatic cover PNC'},
    {'id': 's1_pnc_family', 'ebay_kw': '2024 Bluey Her Family postal numismatic cover PNC', 'search': '2024 Bluey Her Family postal numismatic cover PNC'},
    {'id': 's1_pnc_bingo', 'ebay_kw': '2024 Bingo postal numismatic cover PNC', 'search': '2024 Bingo postal numismatic cover PNC'},
    {'id': 's1_pnc_muffinsocks', 'ebay_kw': '2024 Bluey Muffin Socks postal numismatic cover PNC', 'search': '2024 Bluey Muffin Socks postal numismatic cover PNC'},
    {'id': 's1_pnc_stripes', 'ebay_kw': '2024 Bluey Nana Striped Trixie postal numismatic cover PNC envelope privymark', 'search': '2024 Bluey Nana Striped Trixie postal numismatic cover PNC envelope privymark'},
    {'id': 's1_pnc_radfrisky', 'ebay_kw': '2024 Bluey Rad Frisky postal numismatic cover PNC', 'search': '2024 Bluey Rad Frisky postal numismatic cover PNC'},
    {'id': 's1_pnc_blueyfriends', 'ebay_kw': '2024 Bluey Friends postal numismatic cover PNC', 'search': '2024 Bluey Friends postal numismatic cover PNC'},
    {'id': 's1_pnc_blueybingofriends', 'ebay_kw': '2024 Bluey Bingo Friends postal numismatic cover PNC', 'search': '2024 Bluey Bingo Friends postal numismatic cover PNC'},
    {'id': 's1_pnc_mumdad', 'ebay_kw': '2024 Bluey Chillo Bandit postal numismatic cover PNC envelope privymark', 'search': '2024 Bluey Chillo Bandit postal numismatic cover PNC envelope privymark'},
    {'id': 's1_pnc_grannies', 'ebay_kw': '2024 Bluey Grannies postal numismatic cover PNC', 'search': '2024 Bluey Grannies postal numismatic cover PNC'},
    {'id': 's1_pnc_set_ten', 'ebay_kw': '2024 Bluey PNC set all 10 postal numismatic covers', 'search': '2024 Bluey PNC set all 10 postal numismatic covers'},
    # Further 2024 $1 PNCs + 5th Anniversary proof from RAM 2024-25 Annual
    # Report Appendix E Table 13 (codes 11624-11645; 11635/11637 are distinct
    # records from the 11428/11430 envelope PNCs, not dedupes).
    {'id': 's2_xmas_unc', 'ebay_kw': '2025 $1 Bluey Christmas coloured uncirculated coin', 'search': '2025 $1 Bluey Christmas coloured uncirculated coin'},
    {'id': 's2_xmas_silv', 'ebay_kw': '2025 $1 Bluey Christmas silver proof coin', 'search': '2025 $1 Bluey Christmas silver proof coin'},
    {'id': 's3_rain', 'ebay_kw': '2026 $2 Bluey Rain privy mark uncirculated coin', 'search': '2026 $2 Bluey Rain privy mark uncirculated coin'},
    {'id': 's3_sleepytime', 'ebay_kw': '2026 $2 Bluey Sleepytime privy mark uncirculated', 'search': '2026 $2 Bluey Sleepytime privy mark uncirculated'},
    {'id': 's3_camping', 'ebay_kw': '2026 $2 Bluey Camping privy mark uncirculated coin', 'search': '2026 $2 Bluey Camping privy mark uncirculated coin'},
    {'id': 's3_babyrace', 'ebay_kw': '2026 $2 Bluey Baby Race privy mark uncirculated', 'search': '2026 $2 Bluey Baby Race privy mark uncirculated'},
    {'id': 's3_granny', 'ebay_kw': '2026 $2 Bluey Granny Mobile privy mark uncirculated', 'search': '2026 $2 Bluey Granny Mobile privy mark uncirculated'},
    {'id': 's3_rain_privy', 'ebay_kw': '2026 $2 Bluey Rain Privy Mark coin', 'search': '2026 $2 Bluey Rain Privy Mark coin'},
    {'id': 's3_sleepytime_privy', 'ebay_kw': '2026 $2 Bluey Sleepytime Privy Mark coin', 'search': '2026 $2 Bluey Sleepytime Privy Mark coin'},
    {'id': 's3_camping_privy', 'ebay_kw': '2026 $2 Bluey Camping Privy Mark coin', 'search': '2026 $2 Bluey Camping Privy Mark coin'},
    {'id': 's3_babyrace_privy', 'ebay_kw': '2026 $2 Bluey Baby Race Privy Mark coin', 'search': '2026 $2 Bluey Baby Race Privy Mark coin'},
    {'id': 's3_granny_privy', 'ebay_kw': '2026 $2 Bluey Granny Mobile Privy Mark coin', 'search': '2026 $2 Bluey Granny Mobile Privy Mark coin'},
    {'id': 's3_proof_ab', 'ebay_kw': '2026 $2 Bluey coloured proof aluminium bronze coin', 'search': '2026 $2 Bluey coloured proof aluminium bronze coin'},
    {'id': 's3_proof_silv', 'ebay_kw': '2026 $2 Bluey coloured silver proof coin', 'search': '2026 $2 Bluey coloured silver proof coin'},
    {'id': 's3_maxicard_pack', 'ebay_kw': '2026 Bluey prepaid concertina maxicard pack five designs', 'search': '2026 Bluey prepaid concertina maxicard pack five designs'},
    {'id': 's3_sleepytime_insert', 'ebay_kw': '2026 $2 Bluey Sleepytime Coloured Insert coin', 'search': '2026 $2 Bluey Sleepytime Coloured Insert coin'},
    {'id': 's3_till_bluey', 'ebay_kw': '2026 $2 Bluey coloured till coin circulation', 'search': '2026 $2 Bluey coloured till coin circulation'},
    {'id': 's3_till_bingo', 'ebay_kw': '2026 $2 Bingo coloured till coin circulation', 'search': '2026 $2 Bingo coloured till coin circulation'},
    {'id': 's3_pnc_bluey', 'ebay_kw': '2026 Bluey For Real Life PNC Australia Post', 'search': '2026 Bluey For Real Life PNC Australia Post'},
    {'id': 's3_pnc_bingo', 'ebay_kw': '2026 Bingo Hooray PNC Australia Post', 'search': '2026 Bingo Hooray PNC Australia Post'},
    {'id': 's3_pin_babyrace', 'ebay_kw': '2026 Bluey Baby Race stamp pin cover', 'search': '2026 Bluey Baby Race stamp pin cover'},
    {'id': 's3_pin_camping', 'ebay_kw': '2026 Bluey Camping stamp pin cover', 'search': '2026 Bluey Camping stamp pin cover'},
    {'id': 's3_pin_granny', 'ebay_kw': '2026 Bluey Granny Mobile stamp pin cover', 'search': '2026 Bluey Granny Mobile stamp pin cover'},
    {'id': 's3_pin_rain', 'ebay_kw': '2026 Bluey Rain stamp pin cover', 'search': '2026 Bluey Rain stamp pin cover'},
    {'id': 's3_pin_sleepytime', 'ebay_kw': '2026 Bluey Sleepy Time stamp pin cover', 'search': '2026 Bluey Sleepy Time stamp pin cover'},
    # Series 4 — 2027 Cricket episode collectible coins (RAM launch prices).
    {'id': 's4_cricket_unc', 'ebay_kw': '2027 $1 Bluey Cricket coloured uncirculated coin', 'search': '2027 $1 Bluey Cricket coloured uncirculated coin'},
    {'id': 's4_cricket_proof', 'ebay_kw': '2027 $1 Bluey Cricket coloured silver proof coin', 'search': '2027 $1 Bluey Cricket coloured silver proof coin'},
    {'id': 's3_folder', 'ebay_kw': '2026 $2 Bluey collection folder five coin set', 'search': '2026 $2 Bluey collection folder five coin set'},
    # Series 1 tube sets — these ship in the frontend catalogue and in
    # server.py; they were missing here so they never received live prices.
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


def _load_manual_ebay_sales():
    for candidate in (
        'manual_ebay_sales.json',
        '/var/task/manual_ebay_sales.json',
        os.path.join(os.path.dirname(__file__), '..', 'manual_ebay_sales.json'),
    ):
        try:
            with open(candidate, 'r', encoding='utf-8') as f:
                data = json.load(f)
            coins = data.get('coins') if isinstance(data, dict) else None
            return coins if isinstance(coins, dict) else {}
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


def _has_value(value):
    return value not in (None, '', 0, [], {})


def _usable_ebay(data):
    if not isinstance(data, dict) or data.get('error'):
        return False
    return any(_has_value(data.get(key)) for key in (
        'average_price', 'median_price', 'products', 'historical_products', 'results',
    ))


def _usable_coinxchange(data):
    return isinstance(data, dict) and isinstance(data.get('products'), list) and bool(data.get('fetchedAt'))


DEFAULT_EPN_CAMPAIGN_ID = '5339153744'
DEFAULT_EPN_CUSTOM_ID   = '5339153744'

def _affiliate_url(raw_url, coin_id='', source='ebay'):
    """Serverless mirror of server.affiliate_url (same params, same guards).

    Reads EPN_CAMPAIGN_ID live from the environment so Vercel config and
    tests take effect without a module reload. Defaults to verified campaign
    ID 5339153744 and Custom ID 5339153744 so outbound affiliate tracking is active.
    """
    campaign = os.environ.get('EPN_CAMPAIGN_ID')
    if campaign is None:
        campaign = DEFAULT_EPN_CAMPAIGN_ID
    if not raw_url or not raw_url.startswith('https://www.ebay.com.au'):
        return raw_url
    if not campaign:
        return raw_url
    custom_id = os.environ.get('EPN_CUSTOM_ID')
    if custom_id is None:
        custom_id = DEFAULT_EPN_CUSTOM_ID
    if 'campid=' in raw_url or 'mkevt=' in raw_url:
        if 'customid=blueycoin' in raw_url:
            return re.sub(r'customid=blueycoin[a-zA-Z0-9_-]*', f'customid={custom_id}', raw_url)
        return raw_url
    separator = '&' if '?' in raw_url else '?'
    return (
        f"{raw_url}{separator}"
        f"mkrid=705-53470-19255-0&siteid=15"
        f"&campid={campaign}"
        f"&customid={custom_id}"
        f"&toolid=10001&mkevt=1"
    )


def _tag_ebay_urls(ebay_data, coin_id):
    """Tag outbound eBay URLs in one served eBay payload (copied, not mutated).

    Covers upstream sold-listing product links and the upstream manual
    search URL (response_url). Non-eBay values pass through untouched.
    """
    if not isinstance(ebay_data, dict):
        return ebay_data
    tagged = dict(ebay_data)
    if isinstance(tagged.get('response_url'), str):
        tagged['response_url'] = _affiliate_url(
            tagged['response_url'], coin_id=coin_id, source='ebay_search')
    products = tagged.get('products')
    if isinstance(products, list):
        tagged_products = []
        for product in products:
            if isinstance(product, dict) and isinstance(product.get('link'), str):
                product = dict(product)
                product['link'] = _affiliate_url(
                    product['link'], coin_id=coin_id, source='ebay_sold')
            tagged_products.append(product)
        tagged['products'] = tagged_products
    history = tagged.get('historical_products')
    if isinstance(history, list):
        tagged['historical_products'] = [
            {**item, 'link': _affiliate_url(item.get('link'), coin_id=coin_id, source='ebay_sold')}
            if isinstance(item, dict) and isinstance(item.get('link'), str) else item
            for item in history
        ]
    return tagged


_TITLE_STOP_WORDS = {
    'a', 'and', 'au', 'australia', 'australian', 'coin', 'coins', 'dollar',
    'dollars', 'for', 'in', 'new', 'of', 'the',
    'unc', 'uncirculated', 'with',
}
_NUMBER_WORDS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'twenty': 20, 'fifty': 50,
}
_NAMED_VARIANT_TOKENS = {
    'bingo', 'muffin', 'muffinsocks', 'socks', 'stripe', 'stripes', 'trixie',
    'nana', 'rad', 'frisky', 'friend', 'friends', 'mum', 'dad', 'family',
    'granny', 'grannies', 'rain', 'camping', 'cricket', 'sleepytime', 'heelers',
    'sleepy', 'baby', 'race',
}


def _sold_timestamp(value):
    if not value:
        return None
    for fmt in ('%d %b %Y', '%d %B %Y', '%b %d, %Y', '%B %d, %Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(value).strip(), fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _title_tokens(value):
    return set(re.findall(r'[a-z0-9]+', str(value or '').lower()))


def _expected_quantity(keywords):
    words = re.findall(r'\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty|fifty)\s*(?:-|\s)?\s*(?:coin|coins|piece|pieces|pcs)\b', str(keywords or '').lower())
    if not words:
        return 1
    value = words[-1]
    return int(value) if value.isdigit() else _NUMBER_WORDS[value]


def _product_quantity(title):
    text = str(title or '').lower()
    if re.search(r'\bpair\b|\bpairs\b|\bboth\s+(?:bluey|bingo)\b', text):
        return 2
    match = re.search(r'\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty|fifty)\s*(?:-|\s)?\s*(?:coin|coins|piece|pieces|pcs)\b', text)
    if match:
        value = match.group(1)
        return int(value) if value.isdigit() else _NUMBER_WORDS[value]
    match = re.search(r'\b(?:bag|roll|pack)\s+of\s+(\d+)\b', text)
    if match:
        return int(match.group(1))
    match = re.search(r'\b(\d+)\s*[x×]\s*(?:\$?\d|one|two|three)\b', text)
    if match:
        return int(match.group(1))
    return 1


def _product_matches_coin(product, coin, now=None, max_age_days=90):
    """Conservative sold-record gate: date, identity tokens and product quantity."""
    now = time.time() if now is None else now
    title = str(product.get('title') or '')
    sold_at = _sold_timestamp(product.get('date_sold'))
    age = None if sold_at is None else now - sold_at
    if not title or age is None or age < 0:
        return False
    if max_age_days is not None and age > max_age_days * 24 * 3600:
        return False

    query = str(coin.get('ebay_kw') or '')
    query_tokens = _title_tokens(query)
    title_tokens = _title_tokens(title)
    years = {token for token in query_tokens if re.fullmatch(r'20\d{2}', token)}
    if years and not years.issubset(title_tokens):
        return False

    for variant in {'proof', 'silver', 'coloured', 'colored', 'privy', 'postal', 'pnc', 'card', 'sealed', 'unopened', 'opened', 'special'}:
        if variant in title_tokens and variant not in query_tokens:
            return False
    # ...and the formats the query asks for must be present in the title.
    for group in (('proof',), ('silver',), ('privy', 'privymark'), ('pnc', 'postal'), ('maxicard',), ('sealed', 'unopened'), ('special',)):
        if set(group) & query_tokens and not set(group) & title_tokens:
            return False
    unrequested_names = (title_tokens & _NAMED_VARIANT_TOKENS) - (query_tokens & _NAMED_VARIANT_TOKENS)
    if unrequested_names:
        return False

    identity = query_tokens - _TITLE_STOP_WORDS - years - {'1', '2'}
    # Permit common spelling of Sleepytime as two words while still requiring
    # the distinctive product concept to be present.
    if 'sleepytime' in identity and {'sleepy', 'time'}.issubset(title_tokens):
        title_tokens.add('sleepytime')
    hits = len(identity & title_tokens)
    if hits < min(2, len(identity)):
        return False

    expected = _expected_quantity(query)
    if _product_quantity(title) != expected:
        return False
    return True


def _quality_filter_ebay(data, coin, now=None):
    """Keep older matched sales as history; use only recent sales for current stats."""
    if not isinstance(data, dict):
        return data
    now = time.time() if now is None else now
    current_products = []
    historical_products = []
    # Prefer the current product snapshot when one item ID appears in both
    # current and historical data; a refreshed sale can supersede a stale copy.
    inputs = list(data.get('products') or []) + list(data.get('historical_products') or [])
    seen = set()
    for product in inputs:
        if not isinstance(product, dict):
            continue
        # The CSV importer accepts only rows James has marked Retained and
        # keeps their explicit catalog ID. Preserve that reviewed mapping even
        # when the strict API title matcher rejects a legitimate packaging or
        # product-name variant; the checks below still enforce date, currency,
        # positive price, duplicate and 90-day rules.
        reviewed_csv_match = (
            product.get('source_type') == 'user_imported_csv'
            and product.get('record_status') == 'Retained'
            and product.get('coin_id') == coin.get('id')
        )
        if reviewed_csv_match:
            sold_at = _sold_timestamp(product.get('date_sold'))
            if not product.get('title') or sold_at is None or sold_at > now:
                continue
        elif not _product_matches_coin(product, coin, now=now, max_age_days=None):
            continue
        dedupe_key = str(product.get('item_id') or product.get('link') or (
            product.get('title'), product.get('date_sold'), product.get('sale_price')))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        currency = str(product.get('currency') or '').strip().lower()
        if currency not in {'au', 'aud', 'a$'}:
            continue
        try:
            sale_price = float(str(product.get('sale_price')).replace('$', '').replace(',', '').strip())
        except (TypeError, ValueError):
            continue
        if sale_price <= 0:
            continue
        normalized = {**product, 'sale_price': sale_price}
        age = now - (_sold_timestamp(product.get('date_sold')) or now)
        (current_products if age <= 90 * 24 * 3600 else historical_products).append(normalized)
    current_products.sort(key=lambda p: _sold_timestamp(p.get('date_sold')) or 0, reverse=True)
    historical_products.sort(key=lambda p: _sold_timestamp(p.get('date_sold')) or 0, reverse=True)
    prices = [p['sale_price'] for p in current_products]
    result = dict(data)
    result['products'] = current_products
    result['historical_products'] = historical_products
    result['historical_count'] = len(historical_products)
    result['raw_results'] = data.get('total_results', data.get('results'))
    result['results'] = result['total_results'] = len(current_products)
    result['matched_results'] = len(current_products)
    if prices:
        ordered = sorted(prices)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        result.update({
            'average_price': round(sum(prices) / len(prices), 2),
            'median_price': round(median, 2),
            'min_price': min(prices),
            'max_price': max(prices),
        })
    else:
        for key in ('average_price', 'median_price', 'min_price', 'max_price'):
            result[key] = None
    return result


def _quality_filter_coinxchange(data, coin, now=None):
    """Normalize CoinXchange sold rows and reuse the strict sold-record gate."""
    if not isinstance(data, dict):
        return None
    fetched_at = data.get('fetchedAt')
    if not fetched_at:
        return None
    raw = list(data.get('products', data.get('listings', [])) or []) + list(data.get('historical_products') or [])
    normalized = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        normalized.append({
            **item,
            'title': item.get('title'),
            'sale_price': item.get('sale_price', item.get('price')),
            # Parser accepts only CoinXchange's explicit AU $ price label.
            'currency': item.get('currency') or 'AUD',
            'date_sold': item.get('date_sold', item.get('sold_date')),
        })
    filtered = _quality_filter_ebay({'products': normalized}, coin, now=now)
    products = filtered['products']
    prices = [p['sale_price'] for p in products]
    ordered = sorted(prices)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (
        (ordered[mid - 1] + ordered[mid]) / 2 if ordered else None)
    def _row(p):
        return {
            'price': p['sale_price'],
            'title': p.get('title'),
            'url': p.get('url'),
            'sold_date': p.get('date_sold'),
            'postage': p.get('postage'),
            'currency': 'AUD',
        }
    listings = [_row(p) for p in products]
    # Matched sales older than 90 days stay available for the value-trend
    # chart; they never feed the current median above.
    historical = [_row(p) for p in filtered.get('historical_products') or []]
    return {
        'source': 'CoinXchange',
        'currency': 'AUD',
        'fetchedAt': fetched_at,
        'candidate_results': len(raw),
        'matched_results': len(products),
        'results': len(products),
        'count': len(products),
        'products': listings,
        'historical_products': historical,
        'listings': listings[:10],
        'search_url': data.get('search_url'),
        'average_price': round(sum(prices) / len(prices), 2) if prices else None,
        'median_price': round(median, 2) if median is not None else None,
        'min_price': min(prices) if prices else None,
        'max_price': max(prices) if prices else None,
    }


def _tag_manual_ebay(manual_entry, coin_id):
    """Tag the manual eBay search URL in one coin's manual entry (copied)."""
    if not isinstance(manual_entry, dict):
        return manual_entry
    ebay_entry = manual_entry.get('ebay')
    if not isinstance(ebay_entry, dict) or not isinstance(ebay_entry.get('url'), str):
        return manual_entry
    tagged = dict(manual_entry)
    tagged_ebay = dict(ebay_entry)
    tagged_ebay['url'] = _affiliate_url(
        tagged_ebay['url'], coin_id=coin_id, source='ebay_search')
    tagged['ebay'] = tagged_ebay
    return tagged


def _apply_fetched(result, fetched, coin):
    """Merge only usable upstream data, preserving a durable fallback."""
    if not isinstance(fetched, dict):
        return
    ebay = fetched.get('ebay')
    if _usable_ebay(ebay):
        ebay = dict(ebay)
        ebay['fetchedAt'] = time.time()
        previous = result.get('ebay') or {}
        # A live refresh replaces current summaries but must not erase earlier
        # RapidAPI completed-sale observations that remain useful as history.
        ebay['historical_products'] = list(previous.get('historical_products') or []) + list(previous.get('products') or [])
        result['ebay'] = _quality_filter_ebay(ebay, coin)
    coinxchange = _quality_filter_coinxchange(fetched.get('coinxchange'), coin)
    if _usable_coinxchange(coinxchange):
        if not coinxchange.get('fetchedAt'):
            coinxchange['fetchedAt'] = time.time()
        result['coinxchange'] = coinxchange


def _cached_snapshot(coins, base_cache, manual, manual_ebay_sales=None):
    snapshot = {}
    manual_ebay_sales = manual_ebay_sales or {}
    for coin in coins:
        cid = coin['id']
        cached = base_cache.get(cid, {})
        if not isinstance(cached, dict):
            cached = {}
        cached_ebay = cached.get('ebay') or {}
        if not isinstance(cached_ebay, dict):
            cached_ebay = {}
        imported_ebay = manual_ebay_sales.get(cid) or {}
        if isinstance(imported_ebay, dict) and isinstance(imported_ebay.get('products'), list):
            ebay = {**imported_ebay, **cached_ebay}
            ebay['products'] = (
                list(imported_ebay.get('products') or [])
                + list(cached_ebay.get('products') or [])
            )
            ebay['manual_import'] = imported_ebay.get('import_metadata')
            if imported_ebay.get('response_url'):
                ebay['response_url'] = imported_ebay['response_url']
            fetched_values = []
            for source in (cached_ebay, imported_ebay):
                try:
                    fetched_values.append(float(source.get('fetchedAt')))
                except (TypeError, ValueError):
                    continue
            if fetched_values:
                ebay['fetchedAt'] = max(fetched_values)
        else:
            ebay = cached_ebay
        ebay = _quality_filter_ebay(ebay, coin)
        coinxchange = _quality_filter_coinxchange(cached.get('coinxchange'), coin)
        manual_entry = manual.get(cid)
        if not isinstance(manual_entry, dict):
            manual_entry = {}
        if not isinstance((manual_entry.get('ebay') or {}).get('url'), str):
            sold_search = 'https://www.ebay.com.au/sch/i.html?' + urllib.parse.urlencode({
                '_nkw': coin.get('ebay_kw', coin.get('search', 'Bluey coin')),
                'LH_Sold': '1',
                'LH_Complete': '1',
                '_sop': '15',
            })
            manual_entry = {
                **manual_entry,
                'ebay': {'price': None, 'available': True, 'url': sold_search},
            }
        snapshot[cid] = {
            'ebay': _tag_ebay_urls(ebay, cid),
            'coinxchange': coinxchange,
            'manual': _tag_manual_ebay(manual_entry, cid),
        }
    return snapshot


def _rapidapi_refresh_ids(coins):
    """Choose one bounded batch per cache window for explicit live refresh."""
    if not (RAPIDAPI_KEY and RAPIDAPI_LIVE_REFRESH and RAPIDAPI_REFRESH_LIMIT):
        return set()
    if not coins:
        return set()
    batch_size = RAPIDAPI_REFRESH_LIMIT
    batch_count = (len(coins) + batch_size - 1) // batch_size
    batch = int(time.time() // CACHE_TTL) % batch_count
    start = batch * batch_size
    return {
        coins[index]['id']
        for index in range(start, min(start + batch_size, len(coins)))
    }


def _fetch_coin(coin, fetch_ebay=False, fetch_coinxchange=False):
    cid = coin['id']

    # eBay data is opt-in for callers outside the main cache-first path.
    ebay_data = None
    if fetch_ebay and RAPIDAPI_KEY:
        try:
            ebay_data = _fetch_ebay(coin)
        except Exception as e:
            print(f"eBay fetch failed for {cid}: {type(e).__name__}")

    coinxchange_data = None
    if fetch_coinxchange:
        try:
            raw_listings = _scrape_coinxchange_all(coin)
            if raw_listings is not None:
                coinxchange_data = {
                    'products': raw_listings,
                    'fetchedAt': time.time(),
                    'search_url': 'https://www.coinxchange.com.au/buy?' + urllib.parse.urlencode({
                        'search': coin.get('ebay_kw') or coin.get('search') or '',
                    }),
                }
        except Exception as e:
            print(f"CoinXchange fetch failed for {cid}: {type(e).__name__}")
    return {'ebay': ebay_data, 'coinxchange': coinxchange_data}


def _build_payload(coins=None, fetch_coin=None, deadline=None):
    """Return (snapshot, complete) with a durable, cache-first production path.

    A custom fetcher is retained for focused tests and local diagnostics. The
    deployed handler never uses that path: it serves the committed snapshot and
    only performs a bounded, sequential eBay refresh when explicitly enabled.
    """
    coins = COINS if coins is None else coins
    deadline = FETCH_DEADLINE if deadline is None else deadline
    now = time.time()

    # Return cached snapshot if still fresh
    if 'full' in _cache and now < _last_fetch.get('full', 0):
        return _cache['full'], _cache.get('complete', True)

    base_cache = _load_base_cache()
    manual = _load_manual()
    manual_ebay_sales = _load_manual_ebay_sales()
    if fetch_coin is None:
        snapshot = _cached_snapshot(coins, base_cache, manual, manual_ebay_sales)
        refresh_ids = _rapidapi_refresh_ids(coins)
        complete = True

        if refresh_ids:
            refresh_started = time.monotonic()
            attempted = 0
            for coin in coins:
                if coin['id'] not in refresh_ids:
                    continue
                remaining = deadline - (time.monotonic() - refresh_started)
                if remaining <= 0.1:
                    complete = False
                    break
                attempted += 1
                try:
                    ebay_data = _fetch_ebay(
                        coin,
                        timeout=min(UPSTREAM_TIMEOUT, remaining),
                    )
                    if _usable_ebay(ebay_data):
                        ebay_data = dict(ebay_data)
                        ebay_data['fetchedAt'] = time.time()
                        previous = snapshot[coin['id']].get('ebay') or {}
                        ebay_data['historical_products'] = (
                            list(ebay_data.get('historical_products') or [])
                            + list(previous.get('historical_products') or [])
                            + list(previous.get('products') or [])
                        )
                        if previous.get('manual_import'):
                            ebay_data['manual_import'] = previous['manual_import']
                        snapshot[coin['id']]['ebay'] = _tag_ebay_urls(
                            _quality_filter_ebay(ebay_data, coin), coin['id'])
                except Exception as e:
                    print(f"eBay refresh failed for {coin['id']}: {type(e).__name__}")
            if attempted < len(refresh_ids):
                complete = False

        _cache['full'] = snapshot
        _cache['complete'] = complete
        _last_fetch['full'] = now + (CACHE_TTL if complete else PARTIAL_CACHE_TTL)
        return snapshot, complete

    # Explicit fetchers retain the old deadline-bounded path for tests and
    # diagnostics. Its merge step below still preserves cached data on errors.
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    futures = {pool.submit(fetch_coin, coin): coin for coin in coins}
    done, pending = wait(futures, timeout=deadline)
    # Don't block on stragglers; their sockets time out on their own.
    pool.shutdown(wait=False, cancel_futures=True)

    snapshot = _cached_snapshot(coins, base_cache, manual, manual_ebay_sales)
    for future, coin in futures.items():
        cid = coin['id']
        result = snapshot[cid]
        if future in done:
            try:
                fetched = future.result()
                _apply_fetched(result, fetched, coin)
            except Exception as e:
                print(f"fetch failed for {cid}: {type(e).__name__}")

    complete = not pending
    if pending:
        print(f"prices: {len(pending)}/{len(coins)} coins unfinished at {deadline}s deadline")

    # Save to in-memory cache (stores expiry time)
    _cache['full'] = snapshot
    _cache['complete'] = complete
    _last_fetch['full'] = now + (CACHE_TTL if complete else PARTIAL_CACHE_TTL)
    return snapshot, complete
