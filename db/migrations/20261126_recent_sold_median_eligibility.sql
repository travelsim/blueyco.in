-- Keep conflicting import evidence out of valuation until it is reconciled.
CREATE OR REPLACE VIEW public.recent_sold_median AS
SELECT l.product_id,
       count(*) AS sales,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY l.price_aud::double precision) AS median_aud,
       min(l.price_aud) AS low_aud,
       max(l.price_aud) AS high_aud,
       max(l.date_sold) AS last_sold
FROM public.listings AS l
LEFT JOIN public.review_decisions AS r ON r.listing_id = l.listing_id
WHERE l.status = 'confirmed_sold'
  AND l.date_sold >= CURRENT_DATE - 90
  AND (r.listing_id IS NULL OR r.decision = 'also-in-value')
  AND NOT EXISTS (
    SELECT 1
    FROM public.sale_import_evidence AS e
    WHERE e.listing_id = l.listing_id
      AND (e.median_eligible IS NOT TRUE
           OR e.raw_record -> 'median_eligible' = 'false'::jsonb)
  )
GROUP BY l.product_id;
