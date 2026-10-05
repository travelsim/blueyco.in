# Bluey Coin Tracker deployment and pricing

_Verified 5 October 2026._

## Production

- Canonical URL: <https://blueyco.in>
- Serving platform: Vercel serverless.
- Canonical repository: `travelsim/blueyco.in`.
- Price API: `GET /api/prices`.
- Retailer search API: `POST /api/buy-options`.
- Static site entry point: `index.html`.

`server.py` remains the shared Python library and local development server. Its background thread and local JSON cache are not the production refresh mechanism.

## Pricing evidence and access

- eBay completed-sale results come from the configured RapidAPI integration. Only records with recent dates, Australian currency, matching product identity, and the expected coin quantity may contribute to displayed summaries.
- Saved eBay records older than 90 days are not shown as current prices. Each catalogue item has an eBay completed-sale search link, tagged through the eBay Partner Network when `EPN_CAMPAIGN_ID` is configured.
- Retailer prices in Where to Buy are asking prices. Manual prices require a `checkedAt` timestamp within seven days; otherwise only the source link is returned.
- CoinXchange and Cash Converters prohibit automated access without written permission. Their scrapers are disabled; direct user search links remain. Gumtree is link-only because it blocks automated requests and has no completed-sale history.
- Do not re-enable a source scraper without documented permission or an official supported API.

## Environment

Configure these in the Vercel project settings, never in the repository:

| Variable | Purpose |
| --- | --- |
| `EPN_CAMPAIGN_ID` | eBay Partner Network campaign tag |
| `RAPIDAPI_KEY` | eBay completed-sales API credential |
| `RAPIDAPI_LIVE_REFRESH` | Explicitly enables bounded eBay refresh requests |
| `RAPIDAPI_REFRESH_LIMIT` | Maximum coins refreshed per invocation, capped at five |
| `RAPIDAPI_MIN_INTERVAL` | Minimum interval between upstream requests; at least 1.2 seconds |

The live refresh is opt-in. Check the RapidAPI subscription allowance and Vercel execution limits before enabling scheduled refreshes. There is currently no scheduled refresh configured in this repository.

## Release checks

1. Run focused pricing, buy-options, affiliate, and regression tests.
2. Confirm a Vercel preview passes for the change.
3. After merge, verify production `/`, `/api/prices`, and `/api/buy-options`.
4. Inspect rendered coin cards: stale sold records must not show as current prices, live eBay completed-sale links must carry the EPN tag, and retailer asking prices must be labeled separately.
