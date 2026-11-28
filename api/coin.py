"""Serve one product page per catalogue product at /coin/<slug>.

vercel.json rewrites /coin/<slug> to /api/coin?slug=<slug>. The response is
index.html with that product's own <title>, description, canonical URL, Open
Graph tags, structured data and a static summary that crawlers can read
without JavaScript. In the browser, index.html replaces the summary with the
live product card and previous / next navigation.

Pages come from coin-pages.json, built by scripts/build_coin_pages.js.
"""
import html
import json
import os
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, quote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ORIGIN = 'https://blueyco.in'

_cache = {}


def _read(name):
    if name not in _cache:
        for candidate in (os.path.join(ROOT, name), os.path.join('/var/task', name), name):
            try:
                with open(candidate, 'r', encoding='utf-8') as f:
                    _cache[name] = f.read()
                break
            except OSError:
                continue
        else:
            raise FileNotFoundError(name)
    return _cache[name]


def load_pages():
    data = json.loads(_read('coin-pages.json'))
    return data.get('pages') or []


def find_page(key, pages=None):
    """Return (page, is_canonical) for a slug or a catalogue id."""
    key = (key or '').strip().strip('/').lower()
    if not key:
        return None, False
    for page in pages if pages is not None else load_pages():
        if page['slug'] == key:
            return page, True
    for page in pages if pages is not None else load_pages():
        if str(page['id']).lower() == key:
            return page, False
    return None, False


def _e(value):
    return html.escape(str(value), quote=True)


def _abs(src):
    if not src:
        return None
    if re.match(r'^https?://', src):
        return src
    return ORIGIN + '/' + src.lstrip('/')


def _set_attr(doc, pattern, attr, value):
    """Replace attr="..." inside the first tag matching pattern."""
    match = re.search(pattern, doc)
    if not match:
        return doc
    tag = match.group(0)
    new_tag = re.sub(r'(\b%s=")[^"]*(")' % attr, lambda m: m.group(1) + _e(value) + m.group(2), tag, count=1)
    return doc[:match.start()] + new_tag + doc[match.end():]


def structured_data(page):
    url = ORIGIN + page['url']
    product = {
        '@type': 'Product',
        '@id': url + '#product',
        'name': page['name'],
        'description': page['description'],
        'url': url,
        'category': 'Collectible coins' if page.get('denomination') is not None else 'Collectible stamps and covers',
    }
    image = page.get('image') or {}
    if image.get('src'):
        product['image'] = _abs(image['src'])
    if page.get('productCode'):
        product['sku'] = str(page['productCode'])
    attrs = page.get('attributes') or []
    issuer = 'Royal Australian Mint' if 'RAM' in attrs else ('Australia Post' if 'AUSPOST' in attrs else None)
    if issuer:
        product['brand'] = {'@type': 'Brand', 'name': issuer}
    extra = []
    if page.get('year'):
        extra.append({'@type': 'PropertyValue', 'name': 'Year', 'value': page['year']})
    if page.get('mintage'):
        extra.append({'@type': 'PropertyValue', 'name': 'Mintage', 'value': page['mintage']})
    if page.get('denomination') is not None:
        extra.append({'@type': 'PropertyValue', 'name': 'Denomination', 'value': 'A$%s' % page['denomination']})
    if extra:
        product['additionalProperty'] = extra
    crumbs = {
        '@type': 'BreadcrumbList',
        'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': 'Bluey coins', 'item': ORIGIN + '/'},
            {'@type': 'ListItem', 'position': 2, 'name': page.get('seriesLabel') or 'Bluey', 'item': ORIGIN + '/#all-coins'},
            {'@type': 'ListItem', 'position': 3, 'name': page['name'], 'item': url},
        ],
    }
    graph = {'@context': 'https://schema.org', '@graph': [product, crumbs]}
    return json.dumps(graph, ensure_ascii=False).replace('</', '<\\/')


def static_summary(page, total):
    image = page.get('image') or {}
    rows = []
    if page.get('seriesLabel'):
        rows.append(('Release', page['seriesLabel']))
    if page.get('year'):
        rows.append(('Year', page['year']))
    if page.get('denomination') is not None:
        rows.append(('Denomination', 'A$%s' % page['denomination']))
    if page.get('mintage'):
        rows.append(('Mintage', page['mintage']))
    if page.get('issueQuantity'):
        rows.append(('Issue quantity', '{:,}'.format(page['issueQuantity'])))
    if page.get('mintPrice'):
        rows.append(('Original price', 'A$%s' % page['mintPrice']))
    if page.get('productCode'):
        rows.append(('Product code', page['productCode']))
    if page.get('attributes'):
        rows.append(('Type', ', '.join(page['attributes'])))
    parts = [
        '<section id="coin-page" class="coin-page coin-page-static" data-coin-id="%s">' % _e(page['id']),
        '<nav class="coin-page-crumbs" aria-label="Breadcrumb"><a href="/#all-coins">All Bluey products</a>'
        '<span class="sep"> &rsaquo; </span><span>%s</span></nav>' % _e(page.get('seriesLabel') or 'Bluey'),
        '<h1>%s</h1>' % _e(page['name']),
    ]
    if image.get('src'):
        parts.append('<img src="/%s" alt="%s" width="560" height="360" decoding="async">'
                     % (_e(image['src'].lstrip('/')), _e(image.get('alt') or page['name'])))
    parts.append('<p>%s</p>' % _e(page['description']))
    if rows:
        parts.append('<dl>' + ''.join('<dt>%s</dt><dd>%s</dd>' % (_e(k), _e(v)) for k, v in rows) + '</dl>')
    if page.get('note'):
        parts.append('<p>%s</p>' % _e(page['note']))
    prev, nxt = page['prev'], page['next']
    parts.append(
        '<nav class="coin-page-nav" aria-label="Previous and next product">'
        '<a class="coin-page-step prev" rel="prev" href="/coin/%s"><span class="dir">&larr; Previous</span><span class="name">%s</span></a>'
        '<div class="coin-page-pos"><span class="count">%d of %d</span></div>'
        '<a class="coin-page-step next" rel="next" href="/coin/%s"><span class="dir">Next &rarr;</span><span class="name">%s</span></a>'
        '</nav>' % (_e(prev['slug']), _e(prev['name']), page['position'], total, _e(nxt['slug']), _e(nxt['name'])))
    parts.append('</section>')
    return '\n'.join(parts)


def render_page(page, total, index_html=None):
    doc = index_html if index_html is not None else _read('index.html')
    url = ORIGIN + page['url']
    title = page['title']
    description = page['description']
    image = _abs((page.get('image') or {}).get('src'))

    # Relative asset paths in index.html (coin-images/...) must resolve from the site root.
    doc = doc.replace('<meta charset="UTF-8">', '<meta charset="UTF-8">\n<base href="/">', 1)
    doc = re.sub(r'<title>.*?</title>', '<title>%s</title>' % _e(title), doc, count=1, flags=re.S)
    doc = _set_attr(doc, r'<meta name="description"[^>]*>', 'content', description)
    doc = _set_attr(doc, r'<link rel="canonical"[^>]*>', 'href', url)
    doc = _set_attr(doc, r'<meta property="og:type"[^>]*>', 'content', 'product')
    doc = _set_attr(doc, r'<meta property="og:title"[^>]*>', 'content', title)
    doc = _set_attr(doc, r'<meta property="og:description"[^>]*>', 'content', description)
    doc = _set_attr(doc, r'<meta property="og:url"[^>]*>', 'content', url)
    doc = _set_attr(doc, r'<meta name="twitter:title"[^>]*>', 'content', title)
    doc = _set_attr(doc, r'<meta name="twitter:description"[^>]*>', 'content', description)
    if image:
        doc = _set_attr(doc, r'<meta property="og:image"[^>]*>', 'content', image)
        doc = _set_attr(doc, r'<meta property="og:image:alt"[^>]*>', 'content', (page.get('image') or {}).get('alt') or page['name'])
        doc = _set_attr(doc, r'<meta name="twitter:image"[^>]*>', 'content', image)
    links = '<link rel="prev" href="%s/coin/%s">\n<link rel="next" href="%s/coin/%s">\n' % (
        ORIGIN, quote(page['prev']['slug']), ORIGIN, quote(page['next']['slug']))
    ld = '<script type="application/ld+json">%s</script>\n' % structured_data(page)
    doc = doc.replace('</head>', links + ld + '</head>', 1)
    doc = doc.replace('<body>', '<body class="product-mode">', 1)
    doc = doc.replace('<main id="main-content">', '<main id="main-content">\n' + static_summary(page, total), 1)
    return doc


class handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type='text/html; charset=utf-8', extra=None):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        key = (params.get('slug') or [''])[0]
        if not key:
            match = re.match(r'^/coin/([^/?#]+)/?$', parsed.path)
            key = match.group(1) if match else ''
        try:
            pages = load_pages()
            page, canonical = find_page(key, pages)
        except (OSError, ValueError):
            self._send(503, 'Product pages are unavailable.', 'text/plain; charset=utf-8',
                       {'Cache-Control': 'no-store'})
            return
        if page is None:
            body = _read('index.html').replace(
                '<meta name="robots" content="index, follow, max-image-preview:large">',
                '<meta name="robots" content="noindex, follow">', 1).replace(
                '<meta charset="UTF-8">', '<meta charset="UTF-8">\n<base href="/">', 1)
            self._send(404, body, extra={'Cache-Control': 'public, max-age=0, s-maxage=300'})
            return
        if not canonical:
            self._send(301, '', 'text/plain; charset=utf-8',
                       {'Location': page['url'], 'Cache-Control': 'public, max-age=3600'})
            return
        self._send(200, render_page(page, len(pages)), extra={
            'Cache-Control': 'public, max-age=0, s-maxage=3600, stale-while-revalidate=86400',
            'X-Robots-Tag': 'index, follow',
        })
