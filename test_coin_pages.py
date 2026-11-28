"""Product pages: one page per catalogue product at /coin/<slug>.

coin-pages.json is generated from index.html by scripts/build_coin_pages.js.
These tests keep it in step with the catalogue (without node), check that
every page renders with its own title, description and canonical URL, and
that vercel.json and sitemap.xml route and list every page.
"""
import importlib.util
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / 'index.html').read_text(encoding='utf-8')
MANIFEST = json.loads((ROOT / 'coin-pages.json').read_text(encoding='utf-8'))
PAGES = MANIFEST['pages']

spec = importlib.util.spec_from_file_location('coin_api', ROOT / 'api' / 'coin.py')
coin_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coin_api)


def catalogue_ids():
    start = INDEX.index('window.COINS = [')
    end = INDEX.index('\n];', start)
    return re.findall(r"\{\s*id:\s*'([^']+)'", INDEX[start:end])


class CoinPagesManifest(unittest.TestCase):
    def test_every_catalogue_product_has_one_page(self):
        ids = catalogue_ids()
        self.assertEqual(sorted(ids), sorted(p['id'] for p in PAGES),
                         'coin-pages.json is stale: run node scripts/build_coin_pages.js')
        self.assertEqual(MANIFEST['count'], len(ids))

    def test_slugs_are_unique_and_url_safe(self):
        slugs = [p['slug'] for p in PAGES]
        self.assertEqual(len(slugs), len(set(slugs)))
        for slug in slugs:
            self.assertRegex(slug, r'^[a-z0-9]+(?:-[a-z0-9]+)*$')

    def test_previous_and_next_form_one_loop(self):
        by_id = {p['id']: p for p in PAGES}
        seen, page = set(), PAGES[0]
        for _ in PAGES:
            seen.add(page['id'])
            nxt = by_id[page['next']['id']]
            self.assertEqual(nxt['prev']['id'], page['id'])
            page = nxt
        self.assertEqual(seen, set(by_id))
        self.assertEqual([p['position'] for p in PAGES], list(range(1, len(PAGES) + 1)))

    @unittest.skipUnless(shutil.which('node'), 'node not available')
    def test_manifest_matches_generator(self):
        out = subprocess.run(
            ['node', '-e', "const b=require('./scripts/build_coin_pages.js');"
             "const js=b.load();process.stdout.write(JSON.stringify(js.coinPageOrder(js.COINS)"
             ".map(c=>[c.id,js.coinSlug(c),js.coinPageDescription(c)])))"],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=True)
        expected = json.loads(out.stdout)
        self.assertEqual(expected, [[p['id'], p['slug'], p['description']] for p in PAGES],
                         'coin-pages.json is stale: run node scripts/build_coin_pages.js')


class CoinPageRendering(unittest.TestCase):
    def test_each_page_has_its_own_head_and_summary(self):
        titles = set()
        for page in PAGES:
            doc = coin_api.render_page(page, len(PAGES), INDEX)
            title = re.search(r'<title>(.*?)</title>', doc, re.S).group(1)
            titles.add(title)
            self.assertIn('https://blueyco.in' + page['url'], re.search(r'<link rel="canonical"[^>]*>', doc).group(0))
            self.assertEqual(doc.count('<base href="/">'), 1)
            self.assertIn('<body class="product-mode">', doc)
            self.assertIn('<section id="coin-page"', doc)
            self.assertIn('"@type": "Product"', doc)
            self.assertIn('rel="next" href="/coin/%s"' % page['next']['slug'], doc)
        self.assertEqual(len(titles), len(PAGES))

    def test_lookup_by_slug_and_by_id(self):
        page = PAGES[0]
        self.assertEqual(coin_api.find_page(page['slug'], PAGES), (page, True))
        self.assertEqual(coin_api.find_page(page['id'], PAGES), (page, False))
        self.assertEqual(coin_api.find_page('not-a-product', PAGES), (None, False))

    def test_names_are_escaped(self):
        page = dict(PAGES[0], name='<b>&"x"', title='<b>', description='"d"')
        doc = coin_api.render_page(page, len(PAGES), INDEX)
        self.assertIn('<h1>&lt;b&gt;&amp;&quot;x&quot;</h1>', doc)
        self.assertNotIn('<title><b></title>', doc)


class CoinPageRouting(unittest.TestCase):
    def test_vercel_routes_coin_pages_before_the_catch_all(self):
        cfg = json.loads((ROOT / 'vercel.json').read_text(encoding='utf-8'))
        rewrites = cfg['rewrites']
        self.assertEqual(rewrites[0], {'source': '/coin/:slug', 'destination': '/api/coin?slug=:slug'})

    def test_sitemap_lists_every_page(self):
        sitemap = (ROOT / 'sitemap.xml').read_text(encoding='utf-8')
        for page in PAGES:
            self.assertIn('<loc>https://blueyco.in%s</loc>' % page['url'], sitemap)

    def test_grid_cards_link_to_product_pages(self):
        self.assertIn("titleLink.href = coinPageUrl(coin);", INDEX)
        self.assertIn('initCoinPage();', INDEX)


if __name__ == '__main__':
    unittest.main()
