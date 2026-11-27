# Bluey active listing observations

The production listing ledger is Neon Postgres (`bluey` database). Do not use
the retired OCI database instructions or run schema creation against production.

## Daily observation

Run `scripts/run_neon_daily_check.ps1` from the repository root. The wrapper
obtains the current production connection through Vercel's environment and
supplies the expected Neon branch identity. It does not print credentials.
Python needs `psycopg` from the repository's pinned requirements.

The checker first reads complete product and buy-options snapshots from
`https://blueyco.in`, then validates every product before writing. It uses the
site's product matcher and accepts only canonical eBay item URLs with an item
ID, title and price. It skips state changes on partial/empty results, title
mismatch, duplicate ambiguity, a full ten-item eBay page, or ten combined
priced retailer results. It never confirms a sale. A disappeared observed
listing becomes `likely_sold` for human evidence review; a reappearing listing
returns to `available`. Manually supplied historical sales are not treated as
observed active listings.

For a bounded live pilot, pass `-ProductIds s1_bluey,s1_bingo` to the wrapper.
Do not interpret an absent listing as a sale. A dated sold listing page or
other explicit sale evidence is required before import into confirmed history.
