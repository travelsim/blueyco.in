#!/usr/bin/env python3
"""Create the Supabase schema and optionally import JSON seed data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from storage import Storage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--import-seed",
        action="store_true",
        help="Import ebay_cache.json and price_history.json after creating tables.",
    )
    args = parser.parse_args()

    storage = Storage()
    if not storage.using_postgres:
        print("DATABASE_URL is required.", file=sys.stderr)
        return 2
    storage.ensure_schema()
    if args.import_seed:
        storage.import_seed_files()
        print("Schema ready and seed data imported.")
    else:
        print("Schema ready.")
    storage.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
