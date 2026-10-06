"""Refresh a bounded batch of eBay completed sales into the durable snapshot.

Requires RAPIDAPI_KEY in the environment. A failed request aborts the batch
without changing ebay_cache.json. Previously matched sales are retained and
reclassified as current or historical by the shared pricing quality filter.
"""
import argparse
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from api import prices  # noqa: E402


MAX_BATCH_SIZE = 5


def refresh(offset=0, limit=MAX_BATCH_SIZE):
    if not prices.RAPIDAPI_KEY:
        raise RuntimeError('RAPIDAPI_KEY is not configured; no requests made.')
    if offset < 0:
        raise ValueError('offset must be non-negative')
    if not 1 <= limit <= MAX_BATCH_SIZE:
        raise ValueError(f'limit must be between 1 and {MAX_BATCH_SIZE}')

    cache_path = os.path.join(ROOT, 'ebay_cache.json')
    with open(cache_path, 'r', encoding='utf-8') as stream:
        cache = json.load(stream)

    coins = prices.COINS[offset:offset + limit]
    if not coins:
        raise ValueError(f'offset {offset} is beyond the {len(prices.COINS)} catalog coins')

    updates = {}
    for index, coin in enumerate(coins, offset + 1):
        fetched = prices._fetch_ebay(coin)
        if not isinstance(fetched, dict):
            raise RuntimeError(f"eBay request failed for {coin['id']}; stopping without saving.")
        previous = cache.get(coin['id'], {}).get('ebay') or {}
        merged = {
            **fetched,
            'fetchedAt': time.time(),
            'historical_products': list(previous.get('historical_products') or [])
            + list(previous.get('products') or []),
        }
        filtered = prices._quality_filter_ebay(merged, coin)
        updates[coin['id']] = prices._tag_ebay_urls(filtered, coin['id'])
        print(f"{index}/{len(prices.COINS)} {coin['id']}: "
              f"{len(filtered.get('products') or [])} current, "
              f"{len(filtered.get('historical_products') or [])} historical matched sales")

    for coin_id, ebay_data in updates.items():
        cache.setdefault(coin_id, {})['ebay'] = ebay_data

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
    print(f'Updated {len(updates)} eBay snapshots in {cache_path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offset', type=int, default=0,
                        help='zero-based catalog offset; use successive batches to cover the catalog')
    parser.add_argument('--limit', type=int, default=MAX_BATCH_SIZE,
                        help=f'number of coins to refresh (maximum {MAX_BATCH_SIZE})')
    args = parser.parse_args()
    try:
        refresh(args.offset, args.limit)
    except (RuntimeError, ValueError) as exc:
        parser.error(str(exc))
