-- Bluey Coin Tracker: sold / available / likely-sold ledger (Postgres).
-- One row per eBay listing ever seen. `available` = seen active in the last
-- daily snapshot; `likely_sold` = previously active, now missing (needs human
-- check); `confirmed_sold` = human verified via manual upload (feeds value).
CREATE TABLE IF NOT EXISTS products (
    product_id   TEXT PRIMARY KEY,
    name         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS listings (
    listing_id   TEXT PRIMARY KEY,           -- eBay item_id, or hash for uploads w/o ID
    product_id   TEXT NOT NULL REFERENCES products(product_id),
    title        TEXT NOT NULL DEFAULT '',
    price_aud    NUMERIC,
    currency     TEXT NOT NULL DEFAULT 'AUD',
    condition    TEXT,
    buying_format TEXT,
    date_sold    DATE,                        -- NULL while active
    source       TEXT NOT NULL,               -- ebay_cache | manual_upload | browse_daily | coinxchange
    source_url   TEXT,
    status       TEXT NOT NULL DEFAULT 'available'
                 CHECK (status IN ('available', 'likely_sold', 'confirmed_sold', 'excluded')),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    imported_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_listings_product ON listings (product_id);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings (status);
CREATE INDEX IF NOT EXISTS idx_listings_last_seen ON listings (last_seen_at DESC);

-- Queue for the human: previously available, now gone, with link to verify.
CREATE OR REPLACE VIEW likely_sold_queue AS
SELECT l.listing_id, l.product_id, p.name AS product_name, l.title,
       l.price_aud, l.last_seen_at, l.source_url
FROM listings l JOIN products p ON p.product_id = l.product_id
WHERE l.status = 'likely_sold'
ORDER BY l.last_seen_at DESC;

-- Daily median from confirmed + sold rows in the last 90 days (value source).
CREATE OR REPLACE VIEW recent_sold_median AS
SELECT product_id,
       count(*)                       AS sales,
       percentile_cont(0.5)
         WITHIN GROUP (ORDER BY price_aud) AS median_aud,
       min(price_aud) AS low_aud, max(price_aud) AS high_aud,
       max(date_sold) AS last_sold
FROM listings
WHERE date_sold IS NOT NULL AND status != 'excluded'
  AND date_sold >= current_date - INTERVAL '90 days'
GROUP BY product_id;
