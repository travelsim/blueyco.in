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

- eBay completed-sale results come from the configured RapidAPI integration. Only records with matching product identity, Australian currency and expected quantity contribute to a current summary. Records older than 90 days remain available under Historical eBay sales, clearly excluded from current price statistics. A later live refresh carries previously saved matched records forward instead of discarding them.
- Each catalogue item has an eBay completed-sale search link, tagged through the eBay Partner Network when `EPN_CAMPAIGN_ID` is configured; historical eBay item links are tagged too.
- Card mintage rarity is computed from catalogued mintage figures: 1 is the largest published mintage, 10 the smallest; equal mintages share a score and unpublished mintages are unrated. This is a relative supply indicator, not a market-value estimate.
- Retailer prices in Where to Buy are asking prices. Manual prices require a `checkedAt` timestamp within seven days; otherwise only the source link is returned.
- CoinXchange completed-sale parsing is enabled under James Love's direct instruction on 5 October 2026, with his explicit acknowledgement of the site's automated-access terms. This is owner authorization to accept that terms risk, not permission granted by CoinXchange. Requests use a 1.2-second minimum interval, a six-hour sold-search cache and no login, proxy, CAPTCHA or bot-control bypass. Stop if the site returns 403 or 429; do not retry around the block.
- CoinXchange sold-price summaries require a sale within 90 days, Australian dollars, matching year and at least two identity tokens, matching variant and expected item quantity. Active CoinXchange results are separately filtered and labelled as asking prices. Sold price and postage remain separate fields.
- Cash Converters automation remains disabled; its terms and robots rules prohibit the current automated route. Gumtree stays link-only because it blocks automated requests and has no completed-sale history.
- Nova Coins and Aussie Coins Direct are available as dealer search links only. Their displayed dealer asks must remain distinct from sold prices. No documented data feed/API or automation permission has been verified; do not add a price scraper until the current terms and a supported/authorized feed are confirmed.
- The manual refresh command is `python scripts/refresh_coinxchange.py`. It processes every catalog coin in sequence, writes only after a complete successful run, and leaves the old snapshot unchanged on request failure. Schedule it only after confirming acceptable GitHub Actions and Vercel deployment usage.

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
