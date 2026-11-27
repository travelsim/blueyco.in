# Bluey active listing observations

The production listing ledger is Neon Postgres (`bluey` database). Do not use
the retired OCI database instructions or run schema creation against production.

## Daily observation

Run `scripts/run_neon_daily_check.ps1` from the repository root. The wrapper
obtains the current production connection through Vercel's environment and
supplies the expected Neon branch identity. It does not print credentials.
Python needs `psycopg` from the repository's pinned requirements.

The checker reads complete product snapshots from `https://blueyco.in`, then
uses a tracking-only route backed by eBay Browse API pagination (200 rows per
page, up to eBay's 10,000-result query ceiling). It validates every product
with the site's title matcher and accepts only canonical eBay item URLs with
an item ID, title and price. Any failed page, changing result total, malformed
row, title mismatch or duplicate ambiguity preserves that product's state. A
successful empty snapshot is valid and moves disappeared observed listings to
`likely_sold` for human review. It never confirms a sale. A reappearing listing
returns to `available`. Manually supplied historical sales are not treated as
observed active listings.

For a bounded live pilot, pass `-ProductIds s1_bluey,s1_bingo` to the wrapper.
Do not interpret an absent listing as a sale. A dated sold listing page or
other explicit sale evidence is required before import into confirmed history.
