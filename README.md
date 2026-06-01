## Bluey Coin Tracker

Royal Australian Mint Bluey coins — eBay sold prices + retailer links.

This is the **static Vercel** version of the tracker.

### Deployment

Deployed as a pure static site on Vercel:

1. The site is served directly from this repo.
2. Data comes from two JSON files:
   - `ebay_cache.json` — Recent eBay AU sold prices
   - `retailer_prices.json` — Manual retailer prices and buy links

### Updating Prices

To refresh the data:

1. Update `ebay_cache.json` and/or `retailer_prices.json` locally
2. Commit and push
3. Vercel will automatically redeploy

The full dynamic Python scraper (live fetching + background server) lives in the separate `blueyco.in` repository and is kept untouched.

### Tech

- Pure static HTML + vanilla JavaScript
- Hosted on Vercel
- No backend required for viewing prices
