# BlueyCoin Deployment Notes

_Last updated: 2026-06-06_

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
| `EPN_CAMPAIGN_ID` | eBay Partner Network affiliate links (`campid`) | `5339153744` known locally; must be set on Render |
| `RAPIDAPI_KEY` | eBay sold-price lookup API | needed for fresh eBay data |

Local `.env` is only for `run_local.py` and is gitignored. Render does not read it.

## Cache persistence notes

`server.py` persists runtime cache to:

- `ebay_cache.json`
- `price_history.json`

Render disk can be ephemeral across deploys/restarts unless a persistent disk is configured. The committed JSON files are seed/fallback data only. For robust production persistence, move these to a managed store (Render disk, Postgres, Supabase, Redis/KV, etc.).

## Safe path for now

1. Keep `blueyco.in` canonical on Render.
2. Set `EPN_CAMPAIGN_ID=5339153744` on Render and redeploy.
3. Set `RAPIDAPI_KEY` on Render and redeploy.
4. Push tested changes from the `ws3-backup` branch to a review branch, then merge to `main` only after Render env vars are present.

## If migrating dynamic tracker to Vercel later

Porting work required:

- Rewrite Python API functions into Vercel's current handler shape.
- Add `api/buy-options.py` equivalent to `server.py`'s `POST /api/buy-options`.
- Replace background thread refresh with Vercel Cron.
- Replace local JSON persistence with a DB/KV.
- Update `vercel.json` runtime to a supported Python version compatible with `pyproject.toml`.
- Add integration tests that exercise `/api/prices`, `/api/buy-options`, and affiliate wrapping under the Vercel function environment.
