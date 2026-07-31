"""Durable storage for the Blueycoin service.

When DATABASE_URL is set, data is stored in Postgres, including Supabase
Postgres. Without it, local JSON files remain available for development.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

try:
    from psycopg.types.json import Jsonb
    from psycopg_pool import ConnectionPool
except ImportError:  # Local development can use the JSON fallback.
    Jsonb = None
    ConnectionPool = None


class Storage:
    """Persist price data in Postgres or local JSON files."""

    def __init__(
        self,
        cache_file: str = "ebay_cache.json",
        history_file: str = "price_history.json",
    ) -> None:
        root = Path(__file__).resolve().parent
        self.cache_path = root / cache_file
        self.history_path = root / history_file
        self.database_url = os.environ.get("DATABASE_URL", "").strip()
        self._pool: Any = None

    @property
    def using_postgres(self) -> bool:
        return bool(self.database_url)

    @property
    def mode(self) -> str:
        return "postgres" if self.using_postgres else "json"

    def _get_pool(self) -> Any:
        if not self.using_postgres:
            return None
        if ConnectionPool is None:
            raise RuntimeError(
                "DATABASE_URL is set, but psycopg is not installed. "
                "Install requirements.txt before starting the service."
            )
        if self._pool is None:
            max_size = int(os.environ.get("DB_POOL_MAX_SIZE", "5"))
            self._pool = ConnectionPool(
                conninfo=self.database_url,
                min_size=1,
                max_size=max_size,
                open=True,
            )
        return self._pool

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def ensure_schema(self) -> None:
        """Create the small application schema if it is not present."""
        pool = self._get_pool()
        if pool is None:
            return
        schema_path = Path(__file__).resolve().parent / "db" / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
            conn.commit()

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(
            json.dumps(value, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _epoch(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        return datetime.fromtimestamp(Storage._epoch(value), tz=timezone.utc)

    def load_cache(self) -> dict[str, dict[str, dict[str, Any]]]:
        pool = self._get_pool()
        if pool is None:
            data = self._read_json(self.cache_path, {})
            return data if isinstance(data, dict) else {}

        result: dict[str, dict[str, dict[str, Any]]] = {}
        with pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT coin_id, source, payload, EXTRACT(EPOCH FROM fetched_at)
                FROM price_cache
                ORDER BY coin_id, source
                """
            ).fetchall()
        for coin_id, source, payload, fetched_at in rows:
            entry = dict(payload or {})
            entry["fetchedAt"] = float(fetched_at or 0)
            result.setdefault(coin_id, {})[source] = entry
        return result

    def save_cache(self, data: dict[str, dict[str, dict[str, Any]]]) -> None:
        pool = self._get_pool()
        if pool is None:
            self._write_json(self.cache_path, data)
            return
        rows = []
        for coin_id, sources in data.items():
            if not isinstance(sources, dict):
                continue
            for source, entry in sources.items():
                if not isinstance(entry, dict):
                    continue
                rows.append(
                    (
                        coin_id,
                        source,
                        Jsonb(dict(entry)),
                        self._timestamp(entry.get("fetchedAt")),
                    )
                )
        if not rows:
            return
        with pool.connection() as conn:
            conn.executemany(
                """
                INSERT INTO price_cache (coin_id, source, payload, fetched_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (coin_id, source) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    fetched_at = EXCLUDED.fetched_at
                """,
                rows,
            )
            conn.commit()

    def load_history(self) -> list[dict[str, Any]]:
        pool = self._get_pool()
        if pool is None:
            data = self._read_json(self.history_path, [])
            return data if isinstance(data, list) else []

        result = []
        with pool.connection() as conn:
            rows = conn.execute(
                """
                SELECT snapshot_date, payload
                FROM price_snapshots
                ORDER BY snapshot_date
                """
            ).fetchall()
        for snapshot_date, payload in rows:
            item = dict(payload or {})
            item["date"] = snapshot_date.isoformat()
            result.append(item)
        return result

    def save_history(self, history: list[dict[str, Any]]) -> None:
        pool = self._get_pool()
        if pool is None:
            self._write_json(self.history_path, history)
            return
        rows = []
        for item in history[-365:]:
            raw_date = item.get("date")
            try:
                snapshot_date = date.fromisoformat(str(raw_date))
            except (TypeError, ValueError):
                continue
            payload = {key: value for key, value in item.items() if key != "date"}
            rows.append((snapshot_date, Jsonb(payload)))
        with pool.connection() as conn:
            if rows:
                conn.executemany(
                    """
                    INSERT INTO price_snapshots (snapshot_date, payload)
                    VALUES (%s, %s)
                    ON CONFLICT (snapshot_date) DO UPDATE SET
                        payload = EXCLUDED.payload
                    """,
                    rows,
                )
            conn.execute(
                """
                DELETE FROM price_snapshots
                WHERE snapshot_date < CURRENT_DATE - INTERVAL '365 days'
                """
            )
            conn.commit()

    def load_buy_cache(self, coin_id: str) -> dict[str, Any] | None:
        pool = self._get_pool()
        if pool is None:
            return None
        with pool.connection() as conn:
            row = conn.execute(
                """
                SELECT options, EXTRACT(EPOCH FROM fetched_at)
                FROM buy_options_cache
                WHERE coin_id = %s
                """,
                (coin_id,),
            ).fetchone()
        if row is None:
            return None
        return {"options": row[0] or [], "fetchedAt": float(row[1] or 0)}

    def save_buy_cache(self, coin_id: str, value: dict[str, Any]) -> None:
        pool = self._get_pool()
        if pool is None:
            return
        with pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO buy_options_cache (coin_id, options, fetched_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (coin_id) DO UPDATE SET
                    options = EXCLUDED.options,
                    fetched_at = EXCLUDED.fetched_at
                """,
                (
                    coin_id,
                    Jsonb(value.get("options", [])),
                    self._timestamp(value.get("fetchedAt")),
                ),
            )
            conn.commit()

    def import_seed_files(self) -> None:
        """Import the committed JSON seed files into Postgres."""
        if not self.using_postgres:
            raise RuntimeError("DATABASE_URL is required to import seed files.")
        self.ensure_schema()
        self.save_cache(self._read_json(self.cache_path, {}))
        self.save_history(self._read_json(self.history_path, []))
