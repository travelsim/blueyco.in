import json
import os
import re
import time
import threading
import urllib.request
import urllib.error
import urllib.parse
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

# ── CONFIG ───────────────────────────────────────────────────────────────────
RAPIDAPI_KEY  = os.environ.get('RAPIDAPI_KEY', '')
RAPIDAPI_HOST = 'ebay-average-selling-price.p.rapidapi.com'
RAPIDAPI_URL  = f'https://{RAPIDAPI_HOST}/findCompletedItems'

EBAY_LIVE_HOST = 'real-time-ebay.p.rapidapi.com'
EBAY_LIVE_URL  = f'https://{EBAY_LIVE_HOST}/search'

# eBay Partner Network (EPN) affiliate config
# Set EPN_CAMPAIGN_ID env var after signing up at https://partnernetwork.ebay.com/
EPN_CAMPAIGN_ID = os.environ.get('EPN_CAMPAIGN_ID', '')
EPN_TRACKING_ID = 'blueycoin'

def affiliate_url(raw_url: str, coin_id: str = '', source: str = 'ebay') -> str:
    """Wrap an eBay AU URL with EPN affiliate tracking parameters.

    Returns the original URL unchanged if no campaign is configured or the
    URL is not an eBay AU link.
    """
    if not raw_url or not raw_url.startswith('https://www.ebay.com.au'):
        return raw_url
    if not EPN_CAMPAIGN_ID:
        return raw_url
    custom_id = f'blueycoin-{source}-{coin_id}' if coin_id else 'blueycoin'
    separator = '&' if '?' in raw_url else '?'
    return (
        f"{raw_url}{separator}"
        f"mkrid=705-53470-19255-0&siteid=15"
        f"&campid={EPN_CAMPAIGN_ID}"
        f"&customid={custom_id}"
        f"&toolid=10001&mkevt=1"
    )

CACHE_FILE         = 'ebay_cache.json'
MANUAL_PRICES_FILE = 'retailer_prices.json'
REFRESH_SECS       = 14 * 24 * 3600   # 2 weeks
CHECK_SECS         = 24 * 3600         # check daily whether refresh needed
BUY_CACHE_TTL      = 24 * 3600         # retailer panel cache: 24 h
MAX_BODY_BYTES     = 4_096
RATE_LIMIT_RPM     = 10
RATE_WINDOW_SECS   = 60

STATIC_FILES = {
    '/':            ('index.html',  'text/html; charset=utf-8'),
    '/index.html':  ('index.html',  'text/html; charset=utf-8'),
    '/favicon.svg': ('favicon.svg', 'image/svg+xml'),
}

# ── COIN CATALOGUE ───────────────────────────────────────────────────────────
COINS = [
    {'id': 's1_bluey',      'ebay_kw': '2024 $1 Bluey Dollarbuck Bluey coin uncirculated',       'search': '2024 Bluey Dollarbuck Bluey'},
    {'id': 's1_bingo',      'ebay_kw': '2024 $1 Bluey Dollarbuck Bingo coin uncirculated',       'search': '2024 Bluey Dollarbuck Bingo'},
    {'id': 's1_grannies',   'ebay_kw': '2024 $1 Bluey Dollarbuck Grannies NCLT coin',           'search': '2024 Bluey Dollarbuck Grannies'},
    {'id': 's1_heelers',    'ebay_kw': '2024 $1 Bluey Dollarbuck Heelers NCLT coin',            'search': '2024 Bluey Dollarbuck Heelers'},
    {'id': 's1_set',        'ebay_kw': '2024 $1 Bluey Dollarbuck 3 coin set',                   'search': '2024 Bluey Dollarbuck 3 coin set'},
    {'id': 's2_xmas_unc',   'ebay_kw': '2025 $1 Bluey Christmas coloured uncirculated coin',    'search': '2025 Bluey Christmas uncirculated'},
    {'id': 's2_xmas_silv',  'ebay_kw': '2025 $1 Bluey Christmas silver proof coin',             'search': '2025 Bluey Christmas silver proof'},
    {'id': 's3_folder',     'ebay_kw': '2026 $2 Bluey coin collection folder set',              'search': '2026 Bluey collection folder'},
    {'id': 's3_proof_ab',   'ebay_kw': '2026 $2 Bluey coloured proof aluminium bronze coin',    'search': '2026 Bluey proof aluminium bronze'},
    {'id': 's3_proof_silv', 'ebay_kw': '2026 $2 Bluey coloured silver proof coin',              'search': '2026 Bluey silver proof'},
    {'id': 's3_rain',       'ebay_kw': '2026 $2 Bluey Rain privy mark uncirculated coin',       'search': '2026 Bluey Rain privy mark'},
    {'id': 's3_sleepytime', 'ebay_kw': '2026 $2 Bluey Sleepytime privy mark uncirculated',      'search': '2026 Bluey Sleepytime privy mark'},
    {'id': 's3_camping',    'ebay_kw': '2026 $2 Bluey Camping privy mark uncirculated coin',    'search': '2026 Bluey Camping privy mark'},
    {'id': 's3_babyrace',   'ebay_kw': '2026 $2 Bluey Baby Race privy mark uncirculated',       'search': '2026 Bluey Baby Race privy mark'},
    {'id': 's3_granny',     'ebay_kw': '2026 $2 Bluey Granny Mobile privy mark uncirculated',   'search': '2026 Bluey Granny Mobile privy mark'},
    {'id': 's3_till_bluey', 'ebay_kw': '2026 $2 Bluey coloured till coin circulation',          'search': '2026 Bluey till coin'},
    {'id': 's3_till_bingo', 'ebay_kw': '2026 $2 Bingo coloured till coin circulation',          'search': '2026 Bingo till coin'},
    # ── Series 1 tube-set privy mark coins (new) ──
    {'id': 's1_mumdad',      'ebay_kw': '2024 $1 Bluey Mum & Dad Dollarbuck tube set unc',         'search': '2024 Bluey Mum and Dad tube set'},
    {'id': 's1_muffinsocks', 'ebay_kw': '2024 $1 Bluey Muffin & Socks Dollarbuck tube set unc',    'search': '2024 Bluey Muffin Socks tube set'},
    {'id': 's1_radfrisky',   'ebay_kw': '2024 $1 Bluey Rad & Frisky Dollarbuck tube set unc',      'search': '2024 Bluey Rad Frisky tube set'},
    {'id': 's1_stripetrixie','ebay_kw': '2024 $1 Bluey Stripe Trixie Nana Dollarbuck tube set unc','search': '2024 Bluey Stripe Trixie tube set'},
    {'id': 's1_blueyfriends','ebay_kw': '2024 $1 Bluey Bluey & Friends Dollarbuck tube set unc',   'search': '2024 Bluey friends tube set'},
    {'id': 's1_bingofriends','ebay_kw': '2024 $1 Bluey Bingo & Friends Dollarbuck tube set unc',   'search': '2024 Bluey Bingo friends tube set'},
    {'id': 's1_tube_set',    'ebay_kw': '2024 $1 Bluey 10 coin tube folder set',                   'search': '2024 Bluey 10 coin tube folder set'},
    # ── Series 3 PNCs (new) ──
    {'id': 's3_pnc_bluey',  'ebay_kw': '2026 $2 Bluey For Real Life PNC AusPost',                  'search': '2026 Bluey For Real Life PNC'},
    {'id': 's3_pnc_bingo',  'ebay_kw': '2026 $2 Bingo Hooray PNC AusPost',                         'search': '2026 Bingo Hooray PNC'},
]
COIN_BY_ID = {c['id']: c for c in COINS}

# ── RETAILERS (Buy Now panel) ─────────────────────────────────────────────────
RETAILERS = [
    {
        'id':         'ramint',
        'name':       'Royal Australian Mint',
        'base_url':   'https://eshop.ramint.gov.au',
        'search_url': 'https://eshop.ramint.gov.au/catalogsearch/result/?q={q}',
        'type':       'jsonld',
    },
    {
        'id':         'auspost',
        'name':       'Australia Post',
        'base_url':   'https://auspost.com.au',
        'search_url': 'https://auspost.com.au/shop/search?SearchTerm=bluey',
        'type':       'link_only',
    },
    {
        'id':         'ebay',
        'name':       'eBay AU',
        'base_url':   'https://www.ebay.com.au',
        'search_url': 'https://www.ebay.com.au/sch/i.html?_nkw={q}&LH_BIN=1&_sop=15',
        'type':       'ebay_live',
    },
    {
        'id':         'coinxchange_buy',
        'name':       'CoinXchange',
        'base_url':   'https://www.coinxchange.com.au',
        'search_url': 'https://www.coinxchange.com.au/buy?search={q}',
        'type':       'coinxchange',
    },
]

# ── IN-MEMORY STATE ──────────────────────────────────────────────────────────
_lock       = threading.Lock()
_cache      = {}   # coinId → {'ebay': {...}, 'coinxchange': {...}}
_buy_cache  = {}   # coinId → {'options': [...], 'fetchedAt': float}
_start_time = time.monotonic()  # for health check uptime

# ── BUY-OPTIONS CONCURRENCY CONTROLS ─────────────────────────────────────────
# Hard cap on simultaneous retailer fan-outs. Each scrape can hold a thread for
# up to (n_retailers × per-retailer timeout) seconds, so a small limit prevents
# thread/socket exhaustion from concurrent cache-miss floods.
_BUY_OPTIONS_MAX_CONCURRENT = 3
_buy_options_sem = threading.Semaphore(_BUY_OPTIONS_MAX_CONCURRENT)
# Per-coin in-flight set for single-flight deduplication. A second request for
# a coin whose scrape is already running is rejected immediately (503) instead
# of blocking — blocking would pin threads for the full scrape duration, which
# is exactly the resource exhaustion we are guarding against.
_inflight_lock = threading.Lock()
_inflight: set = set()   # coinIds currently being scraped


class _BusyError(Exception):
    """Raised when scrape capacity is exhausted or coin scrape already in flight."""

# ── RATE LIMITING ────────────────────────────────────────────────────────────
_rate_lock    = threading.Lock()
_rate_buckets = {}

def _is_rate_limited(ip):
    now = time.monotonic()
    with _rate_lock:
        b = _rate_buckets.get(ip)
        if b is None or now - b['window_start'] >= RATE_WINDOW_SECS:
            _rate_buckets[ip] = {'window_start': now, 'count': 1}
            return False
        b['count'] += 1
        return b['count'] > RATE_LIMIT_RPM

# ── CACHE PERSISTENCE ────────────────────────────────────────────────────────
def _load_cache():
    try:
        with open(CACHE_FILE, 'r') as f:
            data = json.load(f)
        with _lock:
            _cache.update(data)
        print(f'Cache loaded: {len(data)} coins')
    except (FileNotFoundError, json.JSONDecodeError):
        pass

def _save_cache():
    with _lock:
        snapshot = dict(_cache)
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(snapshot, f)
    except Exception as e:
        print(f'Cache save error: {e}')

# ── GENERIC HELPERS ──────────────────────────────────────────────────────────
def _http_get(url, accept='text/html', timeout=12):
    req = urllib.request.Request(url, headers={
        'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept':          accept,
        'Accept-Language': 'en-AU,en;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')


def _abs_url(url, base):
    if not url:
        return None
    url = str(url).strip()
    if url.startswith('http'):
        return url
    return base.rstrip('/') + '/' + url.lstrip('/')


def _parse_price(raw):
    """Parse price; handles dollars or cents (Shopify stores price in cents as int)."""
    if raw is None:
        return None
    s = str(raw).strip()
    # If original had no decimal point and value > 200, treat as cents → divide by 100.
    # Coins here range ~$10–$1000+. In cents: 1000–100000+.
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
    """Extracts application/ld+json script block contents."""
    def __init__(self):
        super().__init__()
        self._on  = False
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


def _extract_ld_product(node, base):
    if not isinstance(node, dict):
        return None
    t = node.get('@type', '')
    if isinstance(t, list):
        t = t[0] if t else ''
    if t not in ('Product', 'product'):
        return None
    offers = node.get('offers', {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price     = _parse_price(offers.get('price'))
    avail_str = offers.get('availability', '')
    available = ('InStock' in str(avail_str)) if avail_str else True
    url       = _abs_url(node.get('url', ''), base)
    name      = node.get('name', '')
    return {'name': name, 'price': price, 'available': available, 'url': url}


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
            prod = _extract_ld_product(n, base)
            if prod and prod['price']:
                results.append(prod)
    return results


# ── EBAY REFRESH ─────────────────────────────────────────────────────────────
def _fetch_ebay(coin):
    payload = json.dumps({
        'keywords':           coin['ebay_kw'],
        'excluded_keywords':  '',
        'max_search_results': '60',
        'category_id':        '9355',
        'site_id':            '15',
        'remove_outliers':    'true',
    }).encode()
    req = urllib.request.Request(
        RAPIDAPI_URL, data=payload,
        headers={
            'Content-Type':    'application/json',
            'x-rapidapi-host': RAPIDAPI_HOST,
            'x-rapidapi-key':  RAPIDAPI_KEY,
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# ── COINXCHANGE MARKET PRICE SCRAPER ─────────────────────────────────────────
def _scrape_coinxchange(search_term):
    """
    Scrape CoinXchange buy listings for market price data.
    Tries JSON-LD → embedded JSON → microdata → dollar-amount regex.
    Returns list of {'price': float, 'title': str, 'url': str}.
    """
    q   = urllib.parse.quote(search_term)
    url = f'https://www.coinxchange.com.au/buy?search={q}'
    try:
        html = _http_get(url)
    except Exception as e:
        print(f'CoinXchange fetch error ({search_term}): {e}')
        return []

    listings = []

    # Strategy 1 — JSON-LD
    for prod in _ld_products(html, 'https://www.coinxchange.com.au'):
        if prod['price']:
            listings.append({'price': prod['price'], 'title': prod['name'], 'url': prod['url'] or url})

    # Strategy 2 — embedded JSON objects containing a "price" key
    if not listings:
        for m in re.finditer(r'\{[^{}]{0,400}"price"[^{}]{0,400}\}', html):
            try:
                obj = json.loads(m.group())
                p   = _parse_price(obj.get('price') or obj.get('Price'))
                if p and 5 < p < 10000:
                    listings.append({
                        'price': p,
                        'title': str(obj.get('title') or obj.get('name') or ''),
                        'url':   str(obj.get('url') or obj.get('link') or url),
                    })
            except (json.JSONDecodeError, TypeError):
                continue

    # Strategy 3 — microdata itemprop="price"
    if not listings:
        for m in re.finditer(
            r'itemprop=["\']price["\'][^>]*content=["\']([^"\']+)["\']', html
        ):
            p = _parse_price(m.group(1))
            if p and 5 < p < 10000:
                listings.append({'price': p, 'title': '', 'url': url})

    # Strategy 4 — dollar-amount regex scan
    if not listings:
        raw_prices = re.findall(r'\$\s*([\d,]+(?:\.\d{1,2})?)', html)
        seen = set()
        for raw in raw_prices:
            p = _parse_price(raw)
            if p and 5 < p < 10000 and p not in seen:
                seen.add(p)
                listings.append({'price': p, 'title': '', 'url': url})

    # Deduplicate and sort
    unique, seen_prices = [], set()
    for l in sorted(listings, key=lambda x: x['price']):
        key = round(l['price'], 0)
        if key not in seen_prices:
            seen_prices.add(key)
            unique.append(l)

    return unique[:15]


def _summarise(listings):
    prices = [l['price'] for l in listings if l.get('price')]
    if not prices:
        return None
    return {
        'average_price': round(sum(prices) / len(prices), 2),
        'min_price':     min(prices),
        'max_price':     max(prices),
        'count':         len(prices),
        'listings':      listings[:10],
    }


# ── NEEDS-REFRESH HELPER ──────────────────────────────────────────────────────
def _stale(coin_id, source):
    with _lock:
        entry = _cache.get(coin_id, {}).get(source)
    if not entry:
        return True
    ts = entry.get('fetchedAt', 0)
    if isinstance(ts, str):
        try:
            ts = float(ts)
        except ValueError:
            return True
    return (time.time() - ts) > REFRESH_SECS


# ── BACKGROUND REFRESH THREAD ─────────────────────────────────────────────────
def _refresh_worker():
    _load_cache()
    while True:
        refreshed = 0
        for coin in COINS:
            cid = coin['id']

            # ── eBay ──
            if RAPIDAPI_KEY and _stale(cid, 'ebay'):
                try:
                    result = _fetch_ebay(coin)
                    with _lock:
                        _cache.setdefault(cid, {})['ebay'] = {
                            **result, 'fetchedAt': time.time()
                        }
                    _save_cache()
                    refreshed += 1
                    print(f'eBay OK: {cid}')
                except Exception as e:
                    print(f'eBay FAIL {cid}: {e}')
                time.sleep(5)

            # ── CoinXchange ──
            if _stale(cid, 'coinxchange'):
                try:
                    listings = _scrape_coinxchange(coin['search'])
                    summary  = _summarise(listings)
                    with _lock:
                        _cache.setdefault(cid, {})['coinxchange'] = {
                            **(summary or {}),
                            'fetchedAt': time.time(),
                            'search_url': (
                                'https://www.coinxchange.com.au/buy?search='
                                + urllib.parse.quote(coin['search'])
                            ),
                        }
                    _save_cache()
                    refreshed += 1
                    n = len(listings)
                    print(f'CoinXchange OK: {cid} — {n} listing{"s" if n!=1 else ""}')
                except Exception as e:
                    print(f'CoinXchange FAIL {cid}: {e}')
                time.sleep(3)

        if refreshed:
            print(f'Refresh cycle complete: {refreshed} update(s).')
        time.sleep(CHECK_SECS)


# ── RETAILER BUY-PANEL SCRAPING ───────────────────────────────────────────────
def _shopify_options(retailer, keywords):
    q   = urllib.parse.quote(keywords)
    api = f'{retailer["base_url"]}/search.json?q={q}&type=product'
    try:
        body = _http_get(api, accept='application/json')
        data = json.loads(body)
    except Exception:
        return []
    items = []
    for p in data.get('results', [])[:5]:
        price = _parse_price(p.get('price'))
        href  = _abs_url(p.get('url', ''), retailer['base_url']) \
                or retailer['search_url'].replace('{q}', q)
        items.append({
            'retailer_id': retailer['id'],
            'name':        retailer['name'],
            'price':       price,
            'available':   bool(p.get('available', True)),
            'url':         href,
            'link_only':   price is None,
        })
    return sorted(items, key=lambda x: (x['price'] is None, x['price'] or 9999))


def _jsonld_options(retailer, keywords):
    q   = urllib.parse.quote(keywords)
    url = retailer['search_url'].replace('{q}', q)
    try:
        html = _http_get(url)
    except Exception:
        return []
    items = []
    for prod in _ld_products(html, retailer['base_url']):
        items.append({
            'retailer_id': retailer['id'],
            'name':        retailer['name'],
            'price':       prod['price'],
            'available':   prod['available'],
            'url':         prod['url'] or url,
            'link_only':   False,
        })
    return sorted(items[:3], key=lambda x: x['price'] or 9999)


def _coinxchange_buy_options(retailer, keywords):
    q        = urllib.parse.quote(keywords)
    page_url = retailer['search_url'].replace('{q}', q)
    listings = _scrape_coinxchange(keywords)
    if not listings:
        return [{'retailer_id': retailer['id'], 'name': retailer['name'],
                 'price': None, 'available': True, 'url': page_url, 'link_only': True}]
    return [{
        'retailer_id': retailer['id'],
        'name':        retailer['name'],
        'price':       l['price'],
        'available':   True,
        'url':         l.get('url') or page_url,
        'link_only':   l['price'] is None,
    } for l in listings[:3]]


def _ebay_live_options(retailer, keywords, coin_id=''):
    """
    Fetch active eBay AU Buy It Now listings via RapidAPI real-time-ebay.
    Falls back to a search link if the API call fails or returns no results.
    """
    if not RAPIDAPI_KEY:
        return _link_only_option(retailer, keywords)

    q   = urllib.parse.quote(keywords)
    url = f'{EBAY_LIVE_URL}?query={q}&region=15&buyNow=true&sortBy=price_asc'
    req = urllib.request.Request(url, headers={
        'x-rapidapi-host': EBAY_LIVE_HOST,
        'x-rapidapi-key':  RAPIDAPI_KEY,
        'Accept':          'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f'eBay live API error: {e}')
        return _link_only_option(retailer, keywords)

    # Normalise across known response shapes
    results = (
        data.get('results') or
        data.get('items')   or
        data.get('data', {}).get('results') or
        []
    )

    items = []
    for p in results[:5]:
        # Price may be nested {"value": "32.50"} or a plain string/number
        raw_price = p.get('price') or p.get('currentPrice') or p.get('buyItNowPrice')
        if isinstance(raw_price, dict):
            raw_price = raw_price.get('value') or raw_price.get('amount')
        price = _parse_price(raw_price)

        link = (
            p.get('link') or p.get('url') or p.get('itemUrl') or
            p.get('itemWebUrl') or
            retailer['search_url'].replace('{q}', q)
        )
        safe_link = link if str(link).startswith('http') else retailer['search_url'].replace('{q}', q)

        condition = str(p.get('condition') or p.get('conditionDisplayName') or '')
        available = True  # active listings are by definition available

        if price:
            items.append({
                'retailer_id': retailer['id'],
                'name':        retailer['name'],
                'price':       price,
                'available':   available,
                'url':         affiliate_url(safe_link, coin_id=coin_id, source='ebay_buy'),
                'link_only':   False,
                'subtitle':    condition[:40] if condition else None,
            })

    if not items:
        return _link_only_option(retailer, keywords)

    return sorted(items, key=lambda x: x['price'])[:3]


def _link_only_option(retailer, keywords, coin_id=''):
    q = urllib.parse.quote(keywords)
    raw_url = retailer['search_url'].replace('{q}', q)
    aff_url = affiliate_url(raw_url, coin_id=coin_id, source='ebay_search')
    return [{'retailer_id': retailer['id'], 'name': retailer['name'],
              'price': None, 'available': True,
              'url': aff_url, 'link_only': True}]


def _load_manual():
    try:
        with open(MANUAL_PRICES_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_buy_options(coin_id, keywords):
    # Fast path: valid cached result.
    with _lock:
        cached = _buy_cache.get(coin_id)
    if cached and (time.time() - cached['fetchedAt']) < BUY_CACHE_TTL:
        return cached['options']

    # Single-flight deduplication: if another thread is already scraping this
    # coin, reject immediately rather than blocking. Blocking would pin the
    # caller's thread for the full scrape duration (up to n_retailers × 12 s),
    # which is the same resource exhaustion we are trying to prevent.
    with _inflight_lock:
        if coin_id in _inflight:
            raise _BusyError()
        _inflight.add(coin_id)

    # Global concurrency cap: reject immediately if all scrape slots are taken.
    if not _buy_options_sem.acquire(blocking=False):
        with _inflight_lock:
            _inflight.discard(coin_id)
        raise _BusyError()

    try:
        # Re-check cache now that we hold a semaphore slot (another thread may
        # have just finished the same coin while we acquired the slot).
        with _lock:
            cached = _buy_cache.get(coin_id)
        if cached and (time.time() - cached['fetchedAt']) < BUY_CACHE_TTL:
            return cached['options']

        manual  = _load_manual()
        options = []

        for r in RETAILERS:
            rid = r['id']

            # Manual override always takes priority
            if coin_id in manual and rid in manual[coin_id]:
                m = manual[coin_id][rid]
                q = urllib.parse.quote(keywords)
                options.append({
                    'retailer_id': rid,
                    'name':        r['name'],
                    'price':       m.get('price'),
                    'available':   m.get('available', True),
                    'url':         m.get('url') or r['search_url'].replace('{q}', q),
                    'link_only':   m.get('price') is None,
                })
                continue

            try:
                if r['type'] == 'shopify':
                    results = _shopify_options(r, keywords)
                elif r['type'] == 'jsonld':
                    results = _jsonld_options(r, keywords)
                elif r['type'] == 'coinxchange':
                    results = _coinxchange_buy_options(r, keywords)
                elif r['type'] == 'ebay_live':
                    results = _ebay_live_options(r, keywords, coin_id=coin_id)
                else:
                    results = []
            except Exception as e:
                print(f'Buy-panel scrape fail [{rid}]: {e}')
                results = []

            options.extend(results[:3] if results else _link_only_option(r, keywords, coin_id=coin_id))

        priced    = sorted([o for o in options if not o['link_only'] and o['price'] is not None],
                           key=lambda x: x['price'])
        link_only = [o for o in options if o['link_only'] or o['price'] is None]

        final = priced + link_only
        with _lock:
            _buy_cache[coin_id] = {'options': final, 'fetchedAt': time.time()}
        return final
    finally:
        _buy_options_sem.release()
        with _inflight_lock:
            _inflight.discard(coin_id)


# ── REQUEST HANDLER ──────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, status, body, extra_headers=None):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == '/api/prices':
            with _lock:
                snapshot = dict(_cache)
            self._json(200, snapshot)
            return

        if self.path in ('/health', '/healthz'):
            self._json(200, {
                'status': 'ok',
                'cache_count': len(_cache),
                'uptime_seconds': int(time.monotonic() - _start_time),
            })
            return

        entry = STATIC_FILES.get(self.path)
        if entry is None:
            self.send_response(404)
            self.end_headers()
            return
        fname, ctype = entry
        try:
            with open(fname, 'rb') as f:
                data = f.read()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        if ctype.startswith('text/html'):
            self.send_header('X-Robots-Tag', 'index, follow')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        if self.path == '/api/affiliate-redirect':
            length = int(self.headers.get('Content-Length', 0))
            if length > MAX_BODY_BYTES:
                self._json(413, {'error': 'Request body too large.'})
                return
            try:
                self.connection.settimeout(5)
                try:
                    raw = self.rfile.read(length)
                finally:
                    self.connection.settimeout(None)
                body = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                self._json(400, {'error': 'Invalid JSON.'})
                return
            except OSError:
                self._json(400, {'error': 'Request read timed out.'})
                return
            url = str(body.get('url', ''))
            coin_id = str(body.get('coinId', ''))
            source = str(body.get('source', 'ebay'))
            aff = affiliate_url(url, coin_id=coin_id, source=source)
            self._json(200, {'url': aff, 'is_affiliate': aff != url})
            return

        if self.path != '/api/buy-options':
            self.send_response(404)
            self.end_headers()
            return

        if _is_rate_limited(self.client_address[0]):
            self._json(429, {'error': 'Too many requests.'})
            return

        length = int(self.headers.get('Content-Length', 0))
        if length > MAX_BODY_BYTES:
            self._json(413, {'error': 'Request body too large.'})
            return
        try:
            self.connection.settimeout(5)
            try:
                raw = self.rfile.read(length)
            finally:
                self.connection.settimeout(None)
            body = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self._json(400, {'error': 'Invalid JSON.'})
            return
        except OSError:
            self._json(400, {'error': 'Request read timed out.'})
            return

        coin_id = str(body.get('coinId', ''))
        if not coin_id or coin_id not in COIN_BY_ID:
            self._json(400, {'error': 'Unknown coinId.'})
            return
        keywords = COIN_BY_ID[coin_id]['search']

        try:
            self._json(200, {'options': get_buy_options(coin_id, keywords)})
        except _BusyError:
            self._json(503, {'error': 'Server busy, please try again shortly.'},
                       extra_headers={'Retry-After': '10'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f'Bluey Coin Tracker — http://0.0.0.0:{port}')
    if not RAPIDAPI_KEY:
        print('WARNING: RAPIDAPI_KEY not set — eBay data will not auto-refresh.')
    threading.Thread(target=_refresh_worker, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
