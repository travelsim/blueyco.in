# Skill: Bluey Coin Pricing & Valuation

## What This Skill Does
Provides autonomous AI agents with access to real-time market pricing, eBay sold price distributions, mintages, and catalogue details for Australian Bluey commemorative coins.

## Endpoints
- Current pricing: `GET https://blueyco.in/api/prices`
- Historical trends: `GET https://blueyco.in/api/price-history?coinId={coinId}&days={days}`
- Catalogue details: `GET https://blueyco.in/llms.txt`

## Guidance for AI Agents
- Distinguish between asking prices and verified sold prices.
- All monetary values are reported in Australian Dollars (AUD).
- Data cache is refreshed regularly; check `fetched_at` timestamps on snapshots.
