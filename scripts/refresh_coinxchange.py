"""Refresh one or all CoinXchange completed-sale snapshots for Vercel.

This manual maintenance command writes only dated, product-matched sold data.
It stops on access errors and never retries around a site block.
"""
import argparse
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from api import prices  # noqa: E402


def refresh(limit=None):
    cache_path = os.path.join(ROOT, 'ebay_cache.json')
    with open(cache_path, 'r', encoding='utf-8') as stream:
        cache = json.load(stream)

    coins = prices.COINS[:limit] if limit else prices.COINS
    updates = 0
    for index, coin in enumerate(coins, 1):
        query = coin.get('ebay_kw') or coin.get('search') or ''
        raw = prices._scrape_coinxchange_all(coin)
        if raw is None:
            raise RuntimeError(f"CoinXchange request failed for {coin['id']}; stopping without saving.")
        checked_at = time.time()
        search_url = 'https://www.coinxchange.com.au/buy?' + prices.urllib.parse.urlencode({'search': query})
        evidence = prices._quality_filter_coinxchange({
            'products': raw,
            'fetchedAt': checked_at,
            'search_url': search_url,
        }, coin)
        cache.setdefault(coin['id'], {})['coinxchange'] = evidence
        updates += 1
        print(f"{index}/{len(coins)} {coin['id']}: {evidence['matched_results']} matched of {evidence['candidate_results']} candidate sold records")

    fd, temp_path = tempfile.mkstemp(prefix='ebay-cache-', suffix='.json', dir=ROOT)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            json.dump(cache, stream, separators=(',', ':'), ensure_ascii=False)
        os.replace(temp_path, cache_path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    print(f"Updated {updates} CoinXchange snapshots in {cache_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=None, help='Refresh only the first N catalog entries (for a small pilot).')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be at least 1')
    refresh(args.limit)
