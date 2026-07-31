#!/usr/bin/env python3
"""Run one price refresh cycle for Render Cron or a local operator."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import refresh_once, storage  # noqa: E402


def main() -> int:
    if not storage.using_postgres:
        print("DATABASE_URL is required for scheduled refreshes.", file=sys.stderr)
        return 2
    if not os.environ.get("RAPIDAPI_KEY"):
        print("RAPIDAPI_KEY is not set. CoinXchange refresh will still run.")
    refreshed = refresh_once()
    print(f"Refresh complete: {refreshed} update(s).")
    storage.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
