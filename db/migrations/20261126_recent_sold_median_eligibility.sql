-- Replay-safe reconciliation for recent_sold_median eligibility.
-- Legacy rows without either eligibility record remain value-eligible.
-- Explicit evidence false and reviewer decisions other than also-in-value opt out.
CREATE OR REPLACE VIEW recent_sold_median AS
SELECT l.product_id,
       count(*) AS sales,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY l.price_aud) AS median_aud,
       min(l.price_aud) AS low_aud,
       max(l.price_aud) AS high_aud,
       max(l.date_sold) AS last_sold
FROM listings l
WHERE l.date_sold IS NOT NULL
  AND l.status = 'confirmed_sold'
  AND l.date_sold >= current_date - INTERVAL '90 days'
  AND NOT EXISTS (
      SELECT 1 FROM sale_import_evidence e
      WHERE e.listing_id = l.listing_id AND e.median_eligible = false
  )
  AND NOT EXISTS (
      SELECT 1 FROM review_decisions r
      WHERE r.listing_id = l.listing_id
        AND r.decision IN ('recent-only', 'keep-held', 'not-valid', 'keep-pending', 'keep-out')
  )
GROUP BY l.product_id;
