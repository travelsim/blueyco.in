#!/usr/bin/env node
// Build coin-pages.json and the product section of sitemap.xml from index.html.
//
// Each catalogue product gets its own page at /coin/<slug>. api/coin.py serves
// index.html there with the title, description, canonical and static summary
// from coin-pages.json; the browser then shows the live product card.
// The slug, order, title and description come from the functions in
// index.html itself, so the server pages and the browser always agree.
//
// Run after any catalogue change:  node scripts/build_coin_pages.js
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const INDEX = path.join(ROOT, 'index.html');
const MANIFEST = path.join(ROOT, 'coin-pages.json');
const SITEMAP = path.join(ROOT, 'sitemap.xml');
const ORIGIN = 'https://blueyco.in';

function balanced(src, start, open, close) {
  const i = src.indexOf(open, start);
  if (i < 0) throw new Error('no ' + open + ' after ' + start);
  let depth = 0, quote = null;
  for (let j = i; j < src.length; j++) {
    const ch = src[j];
    if (quote) {
      if (ch === '\\') { j++; continue; }
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === "'" || ch === '"' || ch === '`') { quote = ch; continue; }
    if (ch === '/' && src[j + 1] === '/') { j = src.indexOf('\n', j); if (j < 0) break; continue; }
    if (ch === '/' && src[j + 1] === '*') { j = src.indexOf('*/', j) + 1; continue; }
    if (ch === open) depth++;
    else if (ch === close) { depth--; if (depth === 0) return src.slice(i, j + 1); }
  }
  throw new Error('unbalanced ' + open);
}

function grabFunction(src, name) {
  const marker = 'function ' + name + '(';
  const at = src.indexOf(marker);
  if (at < 0) throw new Error('function ' + name + ' not found in index.html');
  const params = balanced(src, at, '(', ')');
  const bodyStart = at + marker.length - 1 + params.length;
  return 'function ' + name + params + ' ' + balanced(src, bodyStart, '{', '}');
}

function grabConst(src, decl, open, close) {
  const at = src.indexOf(decl);
  if (at < 0) throw new Error(decl + ' not found in index.html');
  return balanced(src, at + decl.length - 1, open, close);
}

function load() {
  const html = fs.readFileSync(INDEX, 'utf8');
  const code = [
    'const COINS = ' + grabConst(html, 'window.COINS = [', '[', ']') + ';',
    'const SERIES_LABELS = ' + grabConst(html, 'const SERIES_LABELS = {', '{', '}') + ';',
    'const COIN_PRODUCT_IMAGES = ' + grabConst(html, 'const COIN_PRODUCT_IMAGES = {', '{', '}') + ';',
    'const COIN_PAGE_SERIES_ORDER = ' + grabConst(html, 'const COIN_PAGE_SERIES_ORDER = [', '[', ']') + ';',
    'const ATTRIBUTES = ' + grabConst(html, 'const ATTRIBUTES = [', '[', ']') + ';',
    ...['getCoinCategory', 'coinAttributes', 'coinSlug', 'coinPageUrl', 'coinPageRank', 'coinPageOrder',
      'coinMintageText', 'coinPageTitle', 'coinPageDescription'].map(name => grabFunction(html, name)),
    'module.exports = { COINS, SERIES_LABELS, COIN_PRODUCT_IMAGES, coinAttributes, coinSlug, coinPageUrl, coinPageOrder, coinMintageText, coinPageTitle, coinPageDescription };',
  ].join('\n');
  const sandbox = { module: { exports: {} } };
  vm.runInNewContext(code, sandbox, { filename: 'index.html#coin-pages' });
  return sandbox.module.exports;
}

function build() {
  const js = load();
  const order = js.coinPageOrder(js.COINS);
  const slugs = new Map();
  order.forEach(coin => {
    const slug = js.coinSlug(coin);
    if (!slug) throw new Error('empty slug for ' + coin.id);
    if (slugs.has(slug)) throw new Error('duplicate slug ' + slug + ': ' + slugs.get(slug) + ' and ' + coin.id);
    slugs.set(slug, coin.id);
  });
  const link = coin => ({ id: coin.id, slug: js.coinSlug(coin), name: coin.name });
  const pages = order.map((coin, i) => {
    const image = js.COIN_PRODUCT_IMAGES[coin.id] || null;
    return {
      id: coin.id,
      slug: js.coinSlug(coin),
      url: js.coinPageUrl(coin),
      name: coin.name,
      title: js.coinPageTitle(coin),
      description: js.coinPageDescription(coin),
      series: coin.series,
      seriesLabel: js.SERIES_LABELS[coin.series] || null,
      year: coin.year || null,
      denomination: coin.denomination == null ? null : coin.denomination,
      mintage: js.coinMintageText(coin) || null,
      issueQuantity: coin.issueQuantity == null ? null : coin.issueQuantity,
      mintPrice: coin.mintPrice == null ? null : coin.mintPrice,
      productCode: coin.productCode || null,
      attributes: [...new Set(js.coinAttributes(coin))],
      image: image ? { src: image.src, alt: image.alt || coin.name } : null,
      note: coin.collectionNote || null,
      position: i + 1,
      prev: link(order[(i - 1 + order.length) % order.length]),
      next: link(order[(i + 1) % order.length]),
    };
  });
  const manifest = { generatedFrom: 'index.html', origin: ORIGIN, count: pages.length, pages };
  fs.writeFileSync(MANIFEST, JSON.stringify(manifest, null, 1) + '\n');

  const start = '  <!-- coin-pages:start (scripts/build_coin_pages.js) -->';
  const end = '  <!-- coin-pages:end -->';
  const block = [start, ...pages.map(p => [
    '  <url>',
    `    <loc>${ORIGIN}${p.url}</loc>`,
    '    <changefreq>daily</changefreq>',
    '    <priority>0.7</priority>',
    '  </url>',
  ].join('\n')), end].join('\n');
  let sitemap = fs.readFileSync(SITEMAP, 'utf8');
  const s = sitemap.indexOf(start), e = sitemap.indexOf(end);
  if (s >= 0 && e > s) sitemap = sitemap.slice(0, s) + block + sitemap.slice(e + end.length);
  else sitemap = sitemap.replace('</urlset>', block + '\n</urlset>');
  fs.writeFileSync(SITEMAP, sitemap);
  return manifest;
}

if (require.main === module) {
  const m = build();
  console.log(`coin-pages.json: ${m.count} product pages; sitemap.xml updated.`);
}

module.exports = { build, load };
