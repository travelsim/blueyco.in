# BlueyCoin Deployment Notes

_Last updated: 2026-08-01_

## Target production architecture

The low-cost production deployment is split into two parts:

1. A free Render Web Service runs `python3 server.py` and serves the site and read APIs.
2. Supabase Postgres stores price cache rows, price history, and retailer buy-option cache data.

Set `RUN_BACKGROUND_REFRESH=0` on the web service. Price data can be refreshed manually with
`python3 scripts/refresh_prices.py` when needed. No Render Cron service is required.

## Current production owner

**Canonical live app:** `https://blueyco.in/` on **Render**.

Evidence from live response headers:

- `rndr-id: ...`
- `x-render-origin-server: BaseHTTP/0.6 Python/3.14.3`
- DNS resolves to Render static IPs behind Cloudflare.

## Vercel status

`https://blueycoin.vercel.app/` is a separate static/prototype deployment from the sister repo `travelsim/blueycoin`.

Do **not** treat Vercel as production for the dynamic tracker until these blockers are resolved:

1. `vercel.json` in this repo is stale. It pins `python3.9` while `pyproject.toml` requires `>=3.11`; current Vercel Python runtime support differs from that old config.
2. Vercel only has `api/prices.py`; it does **not** have the live `POST /api/buy-options` endpoint used by `index.html`.
3. The dynamic Render app depends on a long-lived process model: background refresh thread, in-memory cache, and local JSON cache/history files. Vercel serverless is stateless/frozen between invocations; porting needs a DB/KV plus scheduled refresh.
4. `api/prices.py` is only a fallback/partial serverless price endpoint, not a full replacement for `server.py`.

## Required production environment variables on Render

Set these in the Render service dashboard for `blueyco.in`:

| Var | Purpose | Status |
| --- | --- | --- |
| `DATABASE_URL` | Supabase Postgres session-pooler connection string | required for production |
| `EPN_CAMPAIGN_ID` | eBay Partner Network affiliate links (`campid`) | `5339153744` known locally; must be set on Render |
| `RAPIDAPI_KEY` | eBay sold-price lookup API | needed for fresh eBay data |
| `RUN_BACKGROUND_REFRESH` | Disable the in-process refresh worker on the web service | set to `0` |

Local `.env` is only for `run_local.py` and is gitignored. Render does not read it.

## Supabase setup

Create the Supabase project, then use its IPv4 session-pooler connection string for `DATABASE_URL` on the Render Web Service. Keep the database password in Render secrets and never put it in the repository.

Run the schema and import the committed seed data once:

```bash
DATABASE_URL='your-supabase-session-pooler-url' python3 scripts/migrate.py --import-seed
```

The web service uses Postgres when `DATABASE_URL` is set. Without it, local development falls back to the committed JSON files.

## Cache persistence notes

Local development persists runtime cache to:

- `ebay_cache.json`
- `price_history.json`

Production persistence is handled by Supabase Postgres. The committed JSON files are seed data and local fallback only.

## Safe path for now

1. Create the Supabase project and copy its IPv4 session-pooler connection string.
2. Run `python3 scripts/migrate.py --import-seed` once against Supabase.
3. Connect `travelsim/blueyco.in` to Render using the included `render.yaml` Blueprint.
4. Set `DATABASE_URL`, `RAPIDAPI_KEY`, `EPN_CAMPAIGN_ID`, and `RUN_BACKGROUND_REFRESH=0` on the Web Service.
5. Deploy `main`, then verify `/health` reports `"storage": "postgres"`.
6. When prices need updating, run `python3 scripts/refresh_prices.py` with the production environment variables.

## If migrating dynamic tracker to Vercel later

Porting work required:

- Rewrite Python API functions into Vercel's current handler shape.
- Add `api/buy-options.py` equivalent to `server.py`'s `POST /api/buy-options`.
- Replace background thread refresh with Vercel Cron.
- Replace local JSON persistence with a DB/KV.
- Update `vercel.json` runtime to a supported Python version compatible with `pyproject.toml`.
- Add integration tests that exercise `/api/prices`, `/api/buy-options`, and affiliate wrapping under the Vercel function environment.
