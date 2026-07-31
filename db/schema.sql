CREATE TABLE IF NOT EXISTS price_cache (
    coin_id TEXT NOT NULL,
    source TEXT NOT NULL,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (coin_id, source)
);

CREATE INDEX IF NOT EXISTS price_cache_fetched_at_idx
    ON price_cache (fetched_at);

CREATE TABLE IF NOT EXISTS price_snapshots (
    snapshot_date DATE PRIMARY KEY,
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS buy_options_cache (
    coin_id TEXT PRIMARY KEY,
    options JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS buy_options_cache_fetched_at_idx
    ON buy_options_cache (fetched_at);
