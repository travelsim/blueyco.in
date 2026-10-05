import base64
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
    URL is not an eBay AU link. Never double-tags: a URL that already
    carries EPN parameters is returned unchanged.
    """
    if not raw_url or not raw_url.startswith('https://www.ebay.com.au'):
        return raw_url
    if not EPN_CAMPAIGN_ID:
        return raw_url
    if 'campid=' in raw_url or 'mkevt=' in raw_url:
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

# eBay's own Browse API (OAuth2 client-credentials grant — application-level
# auth, no user login). Preferred over the RapidAPI reseller above when
# configured, since it's eBay's sanctioned public API rather than a paid
# third-party proxy. Covers active/Buy-It-Now listings only — eBay does not
# expose sold/completed-listing search on this free tier.
EBAY_CLIENT_ID     = os.environ.get('EBAY_CLIENT_ID', '')
EBAY_CLIENT_SECRET = os.environ.get('EBAY_CLIENT_SECRET', '')
EBAY_OAUTH_URL     = 'https://api.ebay.com/identity/v1/oauth2/token'
EBAY_OAUTH_SCOPE   = 'https://api.ebay.com/oauth/api_scope'
EBAY_BROWSE_URL    = 'https://api.ebay.com/buy/browse/v1/item_summary/search'
EBAY_MARKETPLACE   = 'EBAY_AU'

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

# ── COIN CATALOGUE (57 tracked products) ────────────────────────────────────
COINS = [
    # Series 1 - 2024 Dollarbucks
    {'id': 's1_bluey', 'ebay_kw': '2024 $1 Bluey Dollarbuck till coin', 'search': '2024 Bluey Dollarbuck Bluey till coin'},
    {'id': 's1_bingo', 'ebay_kw': '2024 $1 Bingo Dollarbuck till coin', 'search': '2024 Bluey Dollarbuck Bingo till coin'},
    {'id': 's1_proof_silver', 'ebay_kw': '2024 $1 Bluey Dollarbucks fine silver coloured proof', 'search': '2024 Bluey Dollarbucks silver proof'},
    {'id': 's1_proof_coloured', 'ebay_kw': '2024 $1 Bluey Dollarbucks coloured proof coin', 'search': '2024 Bluey Dollarbucks coloured proof'},
    {'id': 's1_10_coin_folder_set', 'ebay_kw': '2024 $1 Bluey ten coin collection folder tube set', 'search': '2024 Bluey ten coin collection folder tube'},
    {'id': 's1_coloured_insert_variant', 'ebay_kw': '2024 Bluey special coloured coin one in ten tube set', 'search': '2024 Bluey special coloured tube set coin'},
    {'id': 's1_coloured_bluey', 'ebay_kw': '2024 Bluey coloured uncirculated dollarbuck coin card', 'search': '2024 Bluey coloured uncirculated dollarbuck'},
    {'id': 's1_coloured_heelers', 'ebay_kw': '2024 Bluey Heelers coloured uncirculated dollarbuck', 'search': '2024 Bluey Heelers coloured dollarbuck'},
    {'id': 's1_coloured_grannies', 'ebay_kw': '2024 Bluey Grannies coloured uncirculated dollarbuck', 'search': '2024 Bluey Grannies coloured dollarbuck'},
    {'id': 's1_three_coin_set', 'ebay_kw': '2024 Bluey Dollarbucks coloured three coin set', 'search': '2024 Bluey Dollarbucks three coin set'},
    {'id': 's1_card_bluey', 'ebay_kw': '2024 Bluey $1 privy mark coin in card', 'search': '2024 Bluey privy mark coin in card'},
    {'id': 's1_card_heelers', 'ebay_kw': '2024 Bluey The Heelers $1 privy mark coin card', 'search': '2024 Bluey Heelers privy mark coin in card'},
    {'id': 's1_card_bingo', 'ebay_kw': '2024 Bluey Bingo $1 privy mark coin card', 'search': '2024 Bluey Bingo privy mark coin in card'},
    {'id': 's1_card_muffinsocks', 'ebay_kw': '2024 Bluey Muffin Socks $1 privy mark coin card', 'search': '2024 Bluey Muffin Socks privy mark coin in card'},
    {'id': 's1_card_stripes', 'ebay_kw': '2024 Bluey Stripe Trixie Nana $1 privy mark coin card', 'search': '2024 Bluey Stripe Trixie Nana privy mark coin in card'},
    {'id': 's1_card_radfrisky', 'ebay_kw': '2024 Bluey Rad Frisky $1 privy mark coin card', 'search': '2024 Bluey Rad Frisky privy mark coin in card'},
    {'id': 's1_card_blueyfriends', 'ebay_kw': '2024 Bluey and Friends $1 privy mark coin card', 'search': '2024 Bluey and Friends privy mark coin in card'},
    {'id': 's1_card_blueybingofriends', 'ebay_kw': '2024 Bluey Bingo Friends $1 privy mark coin card', 'search': '2024 Bluey Bingo Friends privy mark coin in card'},
    {'id': 's1_card_mumdad', 'ebay_kw': '2024 Bluey Mum Dad $1 privy mark coin card', 'search': '2024 Bluey Mum Dad privy mark coin in card'},
    {'id': 's1_card_grannies', 'ebay_kw': '2024 Bluey Grannies $1 privy mark coin card', 'search': '2024 Bluey Grannies privy mark coin in card'},
    {'id': 's1_pnc_bluey', 'ebay_kw': '2024 Bluey postal numismatic cover PNC', 'search': '2024 Bluey PNC postal numismatic cover'},
    {'id': 's1_pnc_family', 'ebay_kw': '2024 Bluey Her Family postal numismatic cover PNC', 'search': '2024 Bluey Her Family PNC'},
    {'id': 's1_pnc_bingo', 'ebay_kw': '2024 Bingo postal numismatic cover PNC', 'search': '2024 Bluey Bingo PNC postal numismatic cover'},
    {'id': 's1_pnc_muffinsocks', 'ebay_kw': '2024 Bluey Muffin Socks postal numismatic cover PNC', 'search': '2024 Bluey Muffin Socks PNC'},
    {'id': 's1_pnc_stripes', 'ebay_kw': '2024 Bluey Stripe Trixie Nana postal numismatic cover PNC', 'search': '2024 Bluey Stripe Trixie Nana PNC'},
    {'id': 's1_pnc_radfrisky', 'ebay_kw': '2024 Bluey Rad Frisky postal numismatic cover PNC', 'search': '2024 Bluey Rad Frisky PNC'},
    {'id': 's1_pnc_blueyfriends', 'ebay_kw': '2024 Bluey Friends postal numismatic cover PNC', 'search': '2024 Bluey Friends PNC'},
    {'id': 's1_pnc_blueybingofriends', 'ebay_kw': '2024 Bluey Bingo Friends postal numismatic cover PNC', 'search': '2024 Bluey Bingo Friends PNC'},
    {'id': 's1_pnc_mumdad', 'ebay_kw': '2024 Bluey Mum Dad postal numismatic cover PNC', 'search': '2024 Bluey Mum Dad PNC'},
    {'id': 's1_pnc_grannies', 'ebay_kw': '2024 Bluey Grannies postal numismatic cover PNC', 'search': '2024 Bluey Grannies PNC'},

    # Series 2 - 2025 Christmas
    {'id': 's2_xmas_unc', 'ebay_kw': '2025 $1 Bluey Christmas coloured uncirculated coin', 'search': '2025 Bluey Christmas uncirculated'},
    {'id': 's2_xmas_silv', 'ebay_kw': '2025 $1 Bluey Christmas silver proof coin', 'search': '2025 Bluey Christmas silver proof'},

    # Series 3 - 2026 Bluey $2
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
    {'id': 's3_proof_ab', 'ebay_kw': '2026 $2 Bluey coloured proof aluminium bronze coin', 'search': '2026 Bluey proof aluminium bronze'},
    {'id': 's3_proof_silv', 'ebay_kw': '2026 $2 Bluey coloured silver proof coin', 'search': '2026 Bluey silver proof'},
    {'id': 's3_sleepytime_insert', 'ebay_kw': '2026 $2 Bluey Sleepytime Coloured Insert coin', 'search': '2026 Bluey Sleepytime insert'},
    {'id': 's3_till_bluey', 'ebay_kw': '2026 $2 Bluey coloured till coin circulation', 'search': '2026 Bluey Bingo coloured coin pair'},
    {'id': 's3_till_bingo', 'ebay_kw': '2026 $2 Bingo coloured till coin circulation', 'search': '2026 Bluey Bingo coloured coin pair'},
    {'id': 's3_pnc_bluey', 'ebay_kw': '2026 Bluey For Real Life PNC Australia Post', 'search': '2026 Bluey For Real Life PNC'},
    {'id': 's3_pnc_bingo', 'ebay_kw': '2026 Bingo Hooray PNC Australia Post', 'search': '2026 Bingo Hooray PNC'},
    {'id': 's3_pin_babyrace', 'ebay_kw': '2026 Bluey Baby Race stamp pin cover', 'search': '2026 Bluey Baby Race pin cover'},
    {'id': 's3_pin_camping', 'ebay_kw': '2026 Bluey Camping stamp pin cover', 'search': '2026 Bluey Camping pin cover'},
    {'id': 's3_pin_granny', 'ebay_kw': '2026 Bluey Granny Mobile stamp pin cover', 'search': '2026 Bluey Granny Mobile pin cover'},
    {'id': 's3_pin_rain', 'ebay_kw': '2026 Bluey Rain stamp pin cover', 'search': '2026 Bluey Rain pin cover'},
    {'id': 's3_pin_sleepytime', 'ebay_kw': '2026 Bluey Sleepy Time stamp pin cover', 'search': '2026 Bluey Sleepy Time pin cover'},
    # Series 4 — 2027 Cricket episode collectible coins.
    {'id': 's4_cricket_unc', 'ebay_kw': '2027 $1 Bluey Cricket Rusty coloured uncirculated coin card', 'search': '2027 Bluey Cricket $1 uncirculated'},
    {'id': 's4_cricket_proof', 'ebay_kw': '2027 $1 Bluey Cricket silver proof coin cricket ball tin', 'search': '2027 Bluey Cricket $1 silver proof'},
    {'id': 's3_folder', 'ebay_kw': '2026 $2 Bluey collection folder five coin set', 'search': '2026 Bluey collection folder five coin set'},

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
    {
        'id':         'nova_coins',
        'name':       'Nova Coins · dealer asking listings',
        'base_url':   'https://www.novacoins.com.au',
        'search_url': 'https://www.novacoins.com.au/collections/bluey-coins',
        'type':       'link_only',
    },
    {
        'id':         'aussie_coins_direct',
        'name':       'Aussie Coins Direct · dealer asking listings',
        'base_url':   'https://aussiecoinsdirect.com.au',
        'search_url': 'https://aussiecoinsdirect.com.au/collections/bluey',
        'type':       'link_only',
    },
    {
        'id':         'gumtree',
        'name':       'Gumtree AU',
        'base_url':   'https://www.gumtree.com.au',
        # Gumtree's URL-slug search wants words space-separated (%20, as
        # produced by urllib.parse.quote below) — hyphens are treated as a
        # literal joined phrase and mostly return nothing. With real spaces
        # this resolves to a precise per-coin search.
        'search_url': 'https://www.gumtree.com.au/s-{q}/k0',
        'type':       'link_only',
    },
    {
        'id':         'cashconverters',
        'name':       'Cash Converters',
        'base_url':   'https://www.cashconverters.com.au',
        # The site terms prohibit automated use; query= is also disallowed by
        # robots.txt. A user-clicked search link remains available.
        'search_url': 'https://www.cashconverters.com.au/search-results?q={q}',
        'type':       'link_only',
    },
]

# ── IN-MEMORY STATE ──────────────────────────────────────────────────────────
_lock       = threading.Lock()
_cache      = {}   # coinId → {'ebay': {...}, 'coinxchange': {...}}
_buy_cache  = {}   # coinId → {'options': [...], 'fetchedAt': float}
_start_time = time.monotonic()  # for health check uptime

# eBay Browse API application access token — client-credentials tokens are
# valid for ~2 h and shared across all requests, so it's minted once and
# reused rather than re-fetched per search.
_ebay_token_lock = threading.Lock()
_ebay_token      = {'value': None, 'expires_at': 0}

# Note: _load_price_history() is called below, right after the function
# definition, so the in-memory list is populated before the request
# handler can serve /api/price-history on a cold start.

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

def _client_ip(headers, socket_address):
    """Return the best visitor IP available behind Cloudflare/Render proxies."""
    cf_ip = (headers.get('CF-Connecting-IP') or '').strip()
    if cf_ip:
        return cf_ip

    forwarded_for = (headers.get('X-Forwarded-For') or '').strip()
    if forwarded_for:
        first = forwarded_for.split(',')[0].strip()
        if first:
            return first

    real_ip = (headers.get('X-Real-IP') or '').strip()
    if real_ip:
        return real_ip

    return socket_address[0]

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
        # Normalize fetchedAt to float — some entries may have string timestamps
        # from manual edits or older cache formats.
        for coin_id, sources in data.items():
            if not isinstance(sources, dict):
                continue
            for source, entry in sources.items():
                if isinstance(entry, dict) and 'fetchedAt' in entry:
                    ts = entry['fetchedAt']
                    if isinstance(ts, str):
                        try:
                            entry['fetchedAt'] = float(ts)
                        except ValueError:
                            entry['fetchedAt'] = 0.0  # force re-fetch
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


# ── PRICE HISTORY (persisted snapshots) ──────────────────────────────────────
PRICE_HISTORY_FILE = 'price_history.json'
PRICE_HISTORY_MAX_DAYS = 365   # keep one year of daily snapshots
_price_history = []            # list[dict]; each item is {date, coins: {coinId: {...}}}

def _load_price_history():
    global _price_history
    try:
        with open(PRICE_HISTORY_FILE, 'r') as f:
            data = json.load(f)
        if isinstance(data, list):
            _price_history = data
        else:
            _price_history = []
    except (FileNotFoundError, json.JSONDecodeError):
        _price_history = []

def _save_price_history_to_disk():
    try:
        with open(PRICE_HISTORY_FILE, 'w') as f:
            json.dump(_price_history, f)
    except Exception as e:
        print(f'Price history save error: {e}')

def _save_price_snapshot():
    """Capture today's avg/min/max/sales for every coin in the cache.

    Called after each successful eBay refresh cycle. Deduplicates per-day:
    re-running on the same date overwrites the existing snapshot so partial
    refreshes can complete the picture without polluting the timeline.
    """
    global _price_history
    today = time.strftime('%Y-%m-%d')
    coins_snapshot = {}
    with _lock:
        for cid, sources in _cache.items():
            ebay = sources.get('ebay') or {}
            if not isinstance(ebay, dict) or not ebay.get('average_price'):
                continue
            coins_snapshot[cid] = {
                'avg':  ebay.get('average_price'),
                'min':  ebay.get('min_price'),
                'max':  ebay.get('max_price'),
                'cnt':  ebay.get('total_results', 0) or ebay.get('results', 0),
            }
    if not coins_snapshot:
        return  # no data yet — wait for the first successful fetch
    # overwrite-or-append today's entry
    _price_history = [h for h in _price_history if h.get('date') != today]
    _price_history.append({'date': today, 'coins': coins_snapshot})
    # bound to last N days
    _price_history = sorted(_price_history, key=lambda h: h['date'])[-PRICE_HISTORY_MAX_DAYS:]
    _save_price_history_to_disk()

# Load persisted price history on import so /api/price-history works
# before the background refresh worker has had a chance to run.
_load_price_history()

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


class _TextLinearizer(HTMLParser):
    """Flattens HTML into one text-node-per-line (roughly mirroring a
    browser's rendered text), with the innermost enclosing <a href> tracked
    per line. Used to parse listing pages by line position instead of by
    brittle, changeable CSS class names."""
    SKIP_TAGS = {'script', 'style', 'noscript', 'svg'}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._href_stack = []
        self.lines = []
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag == 'a':
            self._href_stack.append(dict(attrs).get('href'))

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == 'a' and self._href_stack:
            self._href_stack.pop()

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self.lines.append(text)
            self.hrefs.append(self._href_stack[-1] if self._href_stack else None)


def _linearize_html(html):
    p = _TextLinearizer()
    p.feed(html)
    return p.lines, p.hrefs


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
# ── COINXCHANGE MARKET PRICE SCRAPER ─────────────────────────────────────────
# CoinXchange's listing cards are server-rendered twice per item (a mobile
# layout and a desktop layout, toggled by CSS), so the page is linearized to
# text and parsed by fixed line position relative to well-known anchor lines
# ("Sold <date>" for sold listings, the "AU $<price>" line for active ones)
# rather than by CSS class, then deduplicated. This also distinguishes a
# listing's real price ("AU $12.00") from its postage cost
# ("+AU $12.00 postage"), which a plain dollar-amount regex cannot.
_CX_BASE = 'https://www.coinxchange.com.au'
_CX_MIN_INTERVAL = 1.2
_CX_CACHE_TTL_SOLD = 6 * 3600
_CX_CACHE_TTL_ACTIVE = 15 * 60
_cx_request_lock = threading.Lock()
_cx_cache_lock = threading.Lock()
_cx_cache = {}
_cx_last_request = 0.0


def _cx_is_feedback(s):
    return s == '(No feedback)' or bool(re.match(r'^\(\d+\)$', s))


def _cx_dedupe(records, keys):
    seen, out = set(), []
    for r in records:
        k = tuple(r.get(x) for x in keys)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _cx_parse_sold(lines, hrefs):
    """Parse a sold_items=true&sort=3 page into sold listings (for market-price stats)."""
    n, i, records = len(lines), 0, []
    while i < n:
        if lines[i].startswith('Sold '):
            date = lines[i][5:].strip()
            seller = lines[i + 1] if i + 1 < n else ''
            j = i + 2
            k = j + 1 if (j < n and _cx_is_feedback(lines[j])) else j
            if k < n and re.match(r'^\d+%$', lines[k]):
                k += 1

            p_idx = i - 1
            postage = 0.0
            if p_idx >= 0 and lines[p_idx].startswith('+AU $'):
                postage_match = re.search(r'\$([\d,.]+)', lines[p_idx])
                postage = _parse_price(postage_match.group(1)) if postage_match else None
            price = title = href = None
            if p_idx >= 0 and (lines[p_idx] == 'Free postage' or re.match(r'^\+AU \$[\d,.]+ postage$', lines[p_idx])):
                p_idx -= 1
            if p_idx >= 0 and lines[p_idx] == 'Buy It Now':
                p_idx -= 1
            if p_idx >= 0 and re.match(r'^AU \$[\d,.]+$', lines[p_idx]):
                price = _parse_price(lines[p_idx].replace('AU $', ''))
                p_idx -= 1
            if p_idx >= 0 and lines[p_idx] == 'Promoted':
                p_idx -= 1
            if p_idx >= 0 and not _cx_is_feedback(lines[p_idx]) and not re.match(r'^\d+%$', lines[p_idx]):
                title = lines[p_idx]
                href = hrefs[p_idx]

            if title and price:
                records.append({
                    'price': price, 'title': title, 'url': _abs_url(href, _CX_BASE) if href else None,
                    'sold_date': date, 'seller': seller, 'postage': postage, 'currency': 'AUD',
                })
            i = k
        else:
            i += 1
    return _cx_dedupe(records, ['title', 'price', 'sold_date', 'seller'])


def _cx_parse_active(lines, hrefs):
    """Parse a plain (unfiltered) search page into currently-buyable listings."""
    n, i, records = len(lines), 0, []
    while i < n:
        if re.match(r'^AU \$[\d,.]+$', lines[i]):
            price = _parse_price(lines[i].replace('AU $', ''))
            p = i - 1
            if p >= 0 and lines[p] == 'Promoted':
                p -= 1
            title = href = None
            if p >= 0 and not _cx_is_feedback(lines[p]) and not re.match(r'^\d+%$', lines[p]):
                title = lines[p]
                href = hrefs[p]

            f = i + 1
            postage = 0.0
            if f < n and lines[f] == 'Buy It Now':
                f += 1
            if f < n and (lines[f] == 'Free postage' or re.match(r'^\+AU \$[\d,.]+ postage$', lines[f])):
                if lines[f].startswith('+AU $'):
                    postage_match = re.search(r'\$([\d,.]+)', lines[f])
                    postage = _parse_price(postage_match.group(1)) if postage_match else None
                f += 1
            seller = lines[f] if f < n else None
            f += 1
            if f < n and _cx_is_feedback(lines[f]):
                f += 1
            if f < n and re.match(r'^\d+%$', lines[f]):
                f += 1

            if title and price and seller:
                records.append({'price': price, 'title': title, 'url': _abs_url(href, _CX_BASE) if href else None,
                                'postage': postage, 'currency': 'AUD', 'seller': seller})
            i = f
        else:
            i += 1
    return _cx_dedupe(records, ['title', 'price', 'url'])


def _scrape_coinxchange(search_term, sold_only=True):
    """
    Scrape CoinXchange listings.
    sold_only=True  -> recently sold prices, used for market-price stats.
    sold_only=False -> currently active/buyable listings, used for the Buy-Now panel.
    Returns list of {'price': float, 'title': str, 'url': str, ...}.
    """
    key = (str(search_term).strip().lower(), bool(sold_only))
    ttl = _CX_CACHE_TTL_SOLD if sold_only else _CX_CACHE_TTL_ACTIVE
    now = time.time()
    with _cx_cache_lock:
        cached = _cx_cache.get(key)
        if cached and now - cached['fetchedAt'] < ttl:
            return list(cached['listings'])

    params = {'search': search_term}
    if sold_only:
        params['sort'] = '3'
        params['filter[show_only][sold_items]'] = 'true'
    url = f'{_CX_BASE}/buy?{urllib.parse.urlencode(params)}'
    try:
        # User directly authorized bounded CoinXchange collection while
        # acknowledging the site's automated-access terms. No WAF, CAPTCHA,
        # login, proxy or other access-control bypass is used.
        global _cx_last_request
        with _cx_request_lock:
            delay = _CX_MIN_INTERVAL - (time.monotonic() - _cx_last_request)
            if delay > 0:
                time.sleep(delay)
            _cx_last_request = time.monotonic()
            html = _http_get(url, timeout=7)
    except Exception as e:
        print(f'CoinXchange fetch failed: {type(e).__name__}')
        return None

    lines, hrefs = _linearize_html(html)
    listings = _cx_parse_sold(lines, hrefs) if sold_only else _cx_parse_active(lines, hrefs)
    # Preserve the marketplace's sold-order (most recent first) for sale
    # evidence; active asks are sorted by lowest current price for buy-now.
    listings = listings[:15] if sold_only else sorted(listings, key=lambda x: x['price'])[:15]
    with _cx_cache_lock:
        _cx_cache[key] = {'fetchedAt': time.time(), 'listings': list(listings)}
    return listings


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


# ── ADAPTIVE REFRESH FREQUENCY ────────────────────────────────────────────────
def _salty_refresh_secs(coin_id):
    """Adaptive refresh interval based on eBay sales volume.

    Hot coins (50+ completed sales): refresh every 6 hours.
    Active coins (10–49 sales):      refresh every 24 hours.
    Quiet coins (<10 sales):         refresh every 7 days.
    Coins with no data yet:          refresh every 7 days (catch-up mode).
    """
    with _lock:
        entry = _cache.get(coin_id, {}).get('ebay')
    if not entry:
        return 7 * 24 * 3600
    total = entry.get('total_results', 0)
    if total >= 50:
        return 6 * 3600
    elif total >= 10:
        return 24 * 3600
    else:
        return 7 * 24 * 3600


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
    refresh_secs = _salty_refresh_secs(coin_id) if source == 'ebay' else REFRESH_SECS
    return (time.time() - ts) > refresh_secs


# ── BACKGROUND REFRESH THREAD ─────────────────────────────────────────────────
def _refresh_worker():
    _load_cache()
    _load_price_history()
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

        if refreshed:
            print(f'Refresh cycle complete: {refreshed} update(s).')
            _save_price_snapshot()   # record today’s state once per cycle
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


def _cashconverters_options(retailer, keywords):
    """
    Query Cash Converters' public search JSON API for matching listings.
    Unlike eBay/Gumtree this endpoint has no bot-detection at all — a plain
    request with a basic User-Agent returns clean structured JSON, no HTML
    scraping needed. Cash Converters is a real secondhand retailer with
    limited stock, so a narrow per-coin query often legitimately returns
    zero results (not a matching bug) — that's fine, it just means nothing
    of that specific coin is in stock right now.
    """
    # Cash Converters prohibits automated access without express written
    # permission. Keep the user-clicked search option; do not fetch its API.
    return _link_only_option(retailer, keywords)


def _coinxchange_quantity(text):
    s = str(text or '').lower()
    if re.search(r'\bpair\b|\bpairs\b|\bboth\s+(?:bluey|bingo)\b', s):
        return 2
    match = re.search(r'\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty|fifty)\s*(?:-|\s)?\s*(?:coin|coins|piece|pieces|pcs)\b', s)
    if match:
        return int(match.group(1)) if match.group(1).isdigit() else {
            'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
            'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
            'twenty': 20, 'fifty': 50,
        }[match.group(1)]
    match = re.search(r'\b(?:bag|roll|pack)\s+of\s+(\d+)\b', s)
    return int(match.group(1)) if match else 1


def _coinxchange_title_matches(title, keywords):
    title_tokens = set(re.findall(r'[a-z0-9]+', str(title or '').lower()))
    query_tokens = set(re.findall(r'[a-z0-9]+', str(keywords or '').lower()))
    years = {token for token in query_tokens if re.fullmatch(r'20\d{2}', token)}
    if not title_tokens or (years and not years.issubset(title_tokens)):
        return False
    for variant in {'proof', 'silver', 'coloured', 'colored', 'privy', 'postal', 'pnc', 'card'}:
        if variant in title_tokens and variant not in query_tokens:
            return False
    named_variants = {
        'bingo', 'muffin', 'muffinsocks', 'socks', 'stripe', 'stripes', 'trixie',
        'nana', 'rad', 'frisky', 'friend', 'friends', 'mum', 'dad', 'family',
        'granny', 'grannies', 'rain', 'camping', 'cricket', 'rusty', 'sleepytime',
        'sleepy', 'baby', 'race',
    }
    if (title_tokens & named_variants) - (query_tokens & named_variants):
        return False
    stop = {'a', 'and', 'au', 'australia', 'australian', 'coin', 'coins', 'dollar',
            'dollars', 'for', 'in', 'new', 'of', 'the', 'unc', 'uncirculated', 'with'}
    identity = query_tokens - stop - years - {'1', '2'}
    if 'sleepytime' in identity and {'sleepy', 'time'}.issubset(title_tokens):
        title_tokens.add('sleepytime')
    if 'sleepy' in identity and 'sleepytime' in title_tokens:
        title_tokens.add('sleepy')
    if 'time' in identity and 'sleepytime' in title_tokens:
        title_tokens.add('time')
    if len(identity & title_tokens) < min(2, len(identity)):
        return False
    return _coinxchange_quantity(title) == _coinxchange_quantity(keywords)


def _coinxchange_buy_options(retailer, keywords, coin_id=None):
    q        = urllib.parse.quote(keywords)
    page_url = retailer['search_url'].replace('{q}', q)
    listings = _scrape_coinxchange(keywords, sold_only=False)
    listings = [l for l in listings if _coinxchange_title_matches(l.get('title'), keywords)]
    if not listings:
        return [{'retailer_id': retailer['id'], 'name': retailer['name'],
                 'price': None, 'available': True, 'url': page_url, 'link_only': True}]
    return [{
        'retailer_id': retailer['id'],
        'name':        retailer['name'],
        'price':       l['price'],
        'available':   True,
        'url':         l.get('url') or page_url,
        'title':        l.get('title'),
        'currency':     'AUD',
        'price_type':   'asking',
        'link_only':   l['price'] is None,
    } for l in listings[:3]]


def _get_ebay_token():
    """Mint (or reuse) an eBay OAuth2 application access token via the
    client-credentials grant. Raises on failure — callers treat that as
    'Browse API unavailable' and fall back accordingly."""
    with _ebay_token_lock:
        if _ebay_token['value'] and time.time() < _ebay_token['expires_at'] - 60:
            return _ebay_token['value']

    creds = base64.b64encode(f'{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}'.encode()).decode()
    body  = urllib.parse.urlencode({
        'grant_type': 'client_credentials',
        'scope':      EBAY_OAUTH_SCOPE,
    }).encode()
    req = urllib.request.Request(EBAY_OAUTH_URL, data=body, headers={
        'Authorization': f'Basic {creds}',
        'Content-Type':  'application/x-www-form-urlencoded',
    }, method='POST')
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())

    token = data['access_token']
    with _ebay_token_lock:
        _ebay_token['value']      = token
        _ebay_token['expires_at'] = time.time() + data.get('expires_in', 7200)
    return token


def _ebay_browse_search(keywords, limit=5):
    """
    Query eBay's own Browse API for active Buy It Now listings.
    Returns list of {'price', 'title', 'url', 'subtitle'}. Requires
    EBAY_CLIENT_ID/EBAY_CLIENT_SECRET; returns [] if unset or on any error.
    """
    if not (EBAY_CLIENT_ID and EBAY_CLIENT_SECRET):
        return []

    try:
        token = _get_ebay_token()
    except Exception as e:
        print(f'eBay OAuth token error: {e}')
        return []

    params = urllib.parse.urlencode({
        'q':      keywords,
        'limit':  str(limit),
        'filter': 'buyingOptions:{FIXED_PRICE}',
        'sort':   'price',
    })
    req = urllib.request.Request(f'{EBAY_BROWSE_URL}?{params}', headers={
        'Authorization':           f'Bearer {token}',
        'X-EBAY-C-MARKETPLACE-ID': EBAY_MARKETPLACE,
        'Accept':                  'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # Token expired/revoked mid-lifetime — drop it so the next call remints.
            with _ebay_token_lock:
                _ebay_token['value'] = None
        print(f'eBay Browse API error: {e}')
        return []
    except Exception as e:
        print(f'eBay Browse API error: {e}')
        return []

    items = []
    for it in data.get('itemSummaries', []):
        price = _parse_price((it.get('price') or {}).get('value'))
        if not price:
            continue
        condition = it.get('condition') or ''
        items.append({
            'price':    price,
            'title':    it.get('title') or '',
            'url':      it.get('itemWebUrl'),
            'subtitle': condition[:40] if condition else None,
        })
    return items


def _ebay_rapidapi_search(keywords):
    """
    Query the RapidAPI real-time-ebay reseller for active Buy It Now
    listings. Returns list of {'price', 'title', 'url', 'subtitle'}.
    Requires RAPIDAPI_KEY; returns [] if unset or on any error.
    """
    if not RAPIDAPI_KEY:
        return []

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
        return []

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
        if not price:
            continue

        link = p.get('link') or p.get('url') or p.get('itemUrl') or p.get('itemWebUrl')
        condition = str(p.get('condition') or p.get('conditionDisplayName') or '')

        items.append({
            'price':    price,
            'title':    str(p.get('title') or ''),
            'url':      link,
            'subtitle': condition[:40] if condition else None,
        })
    return items


def _ebay_live_options(retailer, keywords, coin_id=''):
    """
    Fetch active eBay AU Buy It Now listings for the Buy-Now panel.
    Prefers eBay's own Browse API (EBAY_CLIENT_ID/EBAY_CLIENT_SECRET); falls
    back to the RapidAPI real-time-ebay reseller (RAPIDAPI_KEY) if that
    yields nothing; falls back to a plain search link if neither is
    configured or both fail. EPN affiliate wrapping is applied either way.
    """
    items = _ebay_browse_search(keywords, limit=5)
    if not items:
        items = _ebay_rapidapi_search(keywords)
    if not items:
        return _link_only_option(retailer, keywords, coin_id=coin_id)

    q = urllib.parse.quote(keywords)
    out = []
    for it in items:
        url = it.get('url')
        safe_link = url if url and str(url).startswith('http') else retailer['search_url'].replace('{q}', q)
        out.append({
            'retailer_id': retailer['id'],
            'name':        retailer['name'],
            'price':       it['price'],
            'available':   True,
            'url':         affiliate_url(safe_link, coin_id=coin_id, source='ebay_buy'),
            'link_only':   False,
            'subtitle':    it.get('subtitle'),
        })

    return sorted(out, key=lambda x: x['price'])[:3]


def _link_only_option(retailer, keywords, coin_id=''):
    q = urllib.parse.quote(keywords)
    raw_url = retailer['search_url'].replace('{q}', q)
    aff_url = affiliate_url(raw_url, coin_id=coin_id, source='ebay_search')
    return [{'retailer_id': retailer['id'], 'name': retailer['name'],
              'price': None, 'available': True,
              'url': aff_url, 'link_only': True}]


def _manual_price_is_fresh(entry):
    """Manual retailer prices require an explicit recent checkedAt timestamp."""
    try:
        checked_at = float(entry.get('checkedAt'))
    except (AttributeError, TypeError, ValueError):
        return False
    age = time.time() - checked_at
    return 0 <= age <= 7 * 24 * 3600


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

            # Manual prices only count as current when recently verified.
            if (coin_id in manual and rid in manual[coin_id]
                    and _manual_price_is_fresh(manual[coin_id][rid])):
                m = manual[coin_id][rid]
                q = urllib.parse.quote(keywords)
                options.append({
                    'retailer_id': rid,
                    'name':        r['name'],
                    'price':       m.get('price'),
                    'available':   m.get('available', True),
                    'price_type':  'asking' if m.get('price') is not None else None,
                    'checkedAt':   m.get('checkedAt'),
                    'url':         affiliate_url(
                        m.get('url') or r['search_url'].replace('{q}', q),
                        coin_id=coin_id, source='ebay_search'),
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
                elif r['type'] == 'cashconverters':
                    results = _cashconverters_options(r, keywords)
                else:
                    results = []
            except Exception as e:
                print(f'Buy-panel scrape fail [{rid}]: {e}')
                results = []

            options.extend(results[:3] if results else _link_only_option(r, keywords, coin_id=coin_id))

        priced    = sorted([o for o in options if not o['link_only'] and o['price'] is not None],
                           key=lambda x: x['price'])
        for option in priced:
            option.setdefault('price_type', 'asking')
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

        if self.path.startswith('/api/price-history'):
            # /api/price-history            → all snapshots for all coins
            # /api/price-history?coinId=X&days=90 → filtered
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            coin_id = (qs.get('coinId') or [''])[0]
            try:
                days = int((qs.get('days') or ['0'])[0])
            except ValueError:
                days = 0
            # filter history list
            hist = list(_price_history)
            if days > 0:
                hist = hist[-days:]
            if coin_id:
                hist = [
                    {'date': h['date'], **(h.get('coins', {}).get(coin_id) or {})}
                    for h in hist if coin_id in (h.get('coins') or {})
                ]
            self._json(200, {
                'snapshots': hist,
                'count':     len(hist),
                'coinId':    coin_id or None,
            })
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

        if _is_rate_limited(_client_ip(self.headers, self.client_address)):
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
