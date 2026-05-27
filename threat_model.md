# Threat Model

## Project Overview

Bluey Coin Tracker is a small public web application for viewing recent eBay Australia sold prices and live retailer buy options for Bluey-themed Royal Australian Mint coins. In production, a Python `ThreadingHTTPServer` in `server.py` serves `index.html`, exposes `GET /api/prices` for cached market data, and exposes `POST /api/buy-options` for on-demand retailer lookups. The browser UI is implemented with vanilla HTML/CSS/JavaScript and loads Chart.js from a public CDN. The server uses a `RAPIDAPI_KEY` environment variable for the live eBay lookup path.

Production-scope assumption for this scan: only files reachable from the deployed app are in scope. The production entry points are `server.py` and `index.html`. `attached_assets/` contains backup/reference artifacts and remains out of scope unless linked or otherwise shown to be reachable from the deployed site.

## Assets

- **RapidAPI server credential and allowance** — the `RAPIDAPI_KEY` in `server.py` authorizes secret-backed upstream eBay requests. Even without disclosing the key, abuse of that capability can consume quota or billable usage.
- **Application availability** — the deployed app is a small single-process Python server. Any request pattern that monopolizes the only request worker prevents visitors from loading both the API and the page itself.
- **Buyer-facing price and link integrity** — cached eBay summaries and live retailer options influence what collectors see and click. Incorrect or attacker-poisoned prices and outbound links directly undermine the app's core function.
- **Shared server-side cache state** — `_cache` and `_buy_cache` are reused across visitors. Data that crosses from untrusted requests or upstream responses into those caches must not let one user tamper with what another user sees.
- **Browser execution context** — any script that runs in origin can read market data, invoke same-origin API calls, and alter the displayed purchase guidance.
- **Third-party dependency trust** — externally hosted Chart.js code and upstream RapidAPI/retailer responses both influence the rendered page.

## Trust Boundaries

- **Public internet to Python server** — all visitors can reach `GET /`, `GET /index.html`, `GET /api/prices`, and `POST /api/buy-options`. The server must treat every request as untrusted and defend its own availability and secret-backed upstream capability.
- **Untrusted request input to shared server-side cache** — `coinId` and `keywords` arrive from the public buy-options endpoint, and any derived retailer data may be cached for later users. Cache keys and cached values must prevent one caller from poisoning cross-user state.
- **Server to RapidAPI and retailer data sources** — `server.py` queries RapidAPI and several retailer sites while attaching the server credential on the eBay live path. Upstream responses are untrusted data that flow back into shared caches and then to browsers.
- **Server to browser** — `GET /api/prices` and `POST /api/buy-options` return JSON that the frontend turns into cards, charts, and outbound links. These responses must be treated as untrusted during rendering.
- **Application code to CDN-hosted JavaScript** — `index.html` loads Chart.js from a third-party CDN, which executes with full origin privileges if delivered to the browser.

## Scan Anchors

- **Production entry points:** `server.py`, `index.html`
- **Highest-risk areas:** `server.py` request handling for `POST /api/buy-options`, especially `_buy_cache` and outbound retailer/eBay lookups; inline `<script>` in `index.html` that renders `/api/prices` and `/api/buy-options` responses
- **Public surface:** the whole app is public and unauthenticated; there is no separate authenticated or admin surface
- **Usually dev-only / lower-priority:** `.local/`, `.agents/`, and `attached_assets/` unless explicitly linked into the deployed page

## Threat Categories

### Denial of Service

The production server is a small public-facing Python process that accepts unauthenticated internet traffic and uses `ThreadingHTTPServer` to spawn request-handling threads while also brokering slow upstream lookups. The application must ensure callers cannot monopolize resources by forcing many concurrent multi-hop retailer/eBay fetches, hold request bodies open indefinitely, or cause cache-miss stampedes that multiply expensive outbound work without strict bounds on request-read time, request volume, concurrency, and external call duration.

### Information Disclosure

The most sensitive secret is the server-side `RAPIDAPI_KEY`. The project must prevent that credential from appearing in browser code, logs, or error responses, and must ensure secret-backed upstream capabilities cannot be exposed in a broader form than the product actually needs.

### Tampering

The app accepts untrusted request parameters and untrusted upstream market data, stores some of the resulting data in shared server-side caches, and then renders prices and outbound links in the DOM. In this project, attacker-controlled request values and third-party responses MUST NOT be able to poison cross-user cache entries, and all rendered text and links MUST continue to use safe DOM APIs and URL validation rather than raw HTML injection.

### Elevation of Privilege

In this architecture, any successful client-side script injection gains the app's full browser privilege set and can issue same-origin requests to the API endpoints. The required guarantee is that attacker-controlled data must never reach executable DOM sinks such as `innerHTML`, and third-party scripts included in the page must be kept to the minimum necessary because they execute with full origin privileges.
