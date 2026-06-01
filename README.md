# Bluey Coin Tracker

Royal Australian Mint Bluey coins — eBay sold prices + retailer links.

## Vercel Static Deployment (recommended)

This repo is now set up for easy static deployment on Vercel:

1. Go to [vercel.com/new](https://vercel.com/new)
2. Import this GitHub repository (`blueycoin`)
3. Vercel will automatically detect it as a static site (thanks to `vercel.json`)
4. Deploy

The site loads data directly from:
- `ebay_cache.json` (eBay sold prices)
- `retailer_prices.json` (manual retailer overrides / search links)

## Updating the data

To refresh prices:
- Run your scraper / update the JSON files locally
- Commit and push the updated `ebay_cache.json` (and optionally `retailer_prices.json`)
- Vercel will redeploy automatically

## Original Python backend

The original `server.py` + live scraping is still in the repo if you want to run it elsewhere (Railway, Render, VPS, etc.).

## UI

Simplified clean card UI (closer to the previous blueyco.in style) for fast static hosting.
