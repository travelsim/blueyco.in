# Blueycoin COO Strategy Report

**Date:** 28 May 2026
**Prepared by:** COO Agent

---

## 1. Current State Assessment

### The Good
- Clean, polished UI with card layout, series tabs, mini price charts, buy panel
- Solid backend: caching, rate limiting, single-flight dedup, threat-aware (CSP, no innerHTML)
- Good SEO: meta tags, Schema.org WebApplication, canonical URLs, robots meta
- Data from 2 sources: eBay sold prices (RapidAPI) + CoinXchange market listings (scraped)
- Live retailer buy panel: RAMint, AusPost, eBay AU, CoinXchange

### Critical Gaps
| Area | Status | Impact |
|------|--------|--------|
| Monetisation | Zero — no affiliate links, no ads, no premium | $0 revenue |
| User engagement | Zero — no newsletter, no accounts, no CTAs | No audience build |
| Search/Filter | None — users scroll through 17 coins manually | Poor UX |
| Data refresh | Every 2 weeks | Too slow for volatile aftermarket |
| Price history | Mini chart only (no persisted trends) | Can't see 3/6/12mo trends |
| Portfolio | Doesn't exist | Missed stickiness |
| Alerts | Doesn't exist | Missed conversion hook |
| Analytics | None | Can't prove value or optimize |

---

## 2. Monetisation Strategy

### Tier 1 — Quick Wins (Week 1)
*Minimal dev effort, immediately recurring*

1. **eBay Partner Network (EPN) affiliate links** — Replace all existing eBay links with tracked affiliate links. Coins & Collectibles category: ~2-4% commission. Avg coin $50-$350 → $1-$14 per qualified sale. Even 200 visitors/mo × 15% click-through × 3% conversion = meaningful passive income.

2. **CoinXchange & RAMint referral links** — Check if CoinXchange has a referral/affiliate program. RAMint (govt mint) likely doesn't, but redirect through EPN for eBay items listed on RAMint.

3. **Google AdSense** — Non-intrusive ad placement below coin cards or in footer. Low RPM ($3-5) but zero ongoing effort.

### Tier 2 — Audience Building (Week 2)
*Captures users, enables future monetisation*

4. **Email Capture** — Newsletter signup with "Notify me when new Bluey coins drop" CTA. Bluey series are hot — collectors want launch alerts. Mailchimp/ConvertKit integration.

5. **Privacy Analytics** — Plausible or Umami to measure traffic, popular coins, click patterns. Informs pricing, ad placement, and content priorities.

### Tier 3 — Premium Features (Weeks 3-4)
*Requires accounts, drives subscription revenue*

6. **User Accounts** — Simple OAuth (Google/GitHub). Needed for portfolio, alerts, premium.

7. **Portfolio Tracker** — Users add coins they own, see total portfolio value vs mint cost, P&L per coin. Core stickiness driver.

8. **Price Alerts** — Email when a tracked coin hits target price on eBay. $5-10/mo feature.

### Tier 4 — Growth & Partnerships (Week 5+)
*Scaling revenue*

9. **Sponsored Dealer Listings** — Coin dealers pay $50-200/mo for featured placement in buy panel.

10. **Premium Tier** — Portfolio + Alerts + Early data access at $5-10/mo. Target 10-20 subscribers in first 3 months.

---

## 3. Revenue Projection

| Stream | Month 1 | Month 2 | Month 3 | Annual Run Rate |
|--------|---------|---------|---------|-----------------|
| EPN Affiliates | $5-10 | $15-30 | $30-60 | $360-720 |
| AdSense | $2-5 | $5-10 | $10-20 | $120-240 |
| Sponsored Dealers | $0 | $50-100 | $100-200 | $1,200-2,400 |
| Premium Subscriptions | $0 | $0 | $50-100 | $600-1,200 |
| **Total** | **$7-15** | **$70-140** | **$190-380** | **$2,280-4,560** |

---

## 4. Delegated Workstreams → cod3r

### WS-1: Affiliate Links (PRIORITY)
**Specification:**
- Sign up for eBay Partner Network (EPN) AU
- Create a server-side function that transforms any eBay AU URL → EPN tracked URL with `?mkcid=1&mkrid=705-53470-19255-0&siteid=15&campid=YOUR_CAMPAIGN_ID&customid=blueycoin-{coinId}`
- Apply to ALL eBay links in the app:
  - "Where to Buy" eBay AU links in buy panel
  - Recent sale "↗" view-on-eBay links
  - The hard-coded eBay AU links in the coin data (buy-btn fallback URLs)
- For CoinXchange links, investigate if they have an affiliate program at partner@coinxchange.com.au
- For RAMint/AusPost links — these are government sites, unlikely to have affiliate programs, leave as-is
- Add `rel="sponsored"` to all affiliate links for compliance
- Test: verify tracking cookie is set and commission qualifies

### WS-2: Analytics + Email Capture
**Specification:**
- Add Plausible Analytics (self-hosted or plausible.io) — lightweight, privacy-compliant, no GDPR issues
- Add email signup form in page footer:
  - Input: email address
  - Service: Mailchimp (free tier up to 500 contacts)
  - CTA: "Get notified when new Bluey coins drop" + "Weekly price digest"
  - POST to server → server forwards to Mailchimp API (keeps API key server-side)
- Add a "New Series Alert" checkbox in the email form
- No popups — keep it clean, inline below the coin grid

### WS-3: Technical Improvements
**Specification:**
- Increase refresh frequency from 14 days to:
  - Every 6 hours for high-volume coins (10+ recent sales)
  - Every 24 hours for medium-volume
  - Every 7 days for low-volume (0-2 sales)
- Add search bar at top of page — filters coins by name/keyword in real-time (client-side)
- Add sort dropdown: by Premium % (high→low), by eBay Avg Sold, by Mintage, by Mint Price
- Add price history persistence: store daily snapshots in a JSON file or SQLite DB
- Consider migrating from RapidAPI to direct eBay Browse API (eBay Developer Program — free tier has calls/month quota)

### WS-4: User Accounts + Portfolio Tracker
**Specification:**
- Add simple auth via OAuth (Google Sign-In or GitHub — one provider is enough)
- No password storage needed (delegated to OAuth)
- Portfolio feature:
  - POST /api/portfolio — add coin (coinId, quantity, purchasePrice, purchaseDate)
  - GET /api/portfolio — return user's portfolio with current market values
  - Frontend: portfolio dashboard showing total value, P&L, per-coin breakdown
  - Store in JSON file or SQLite (simple, no DB server needed)
- "Add to Portfolio" button on each coin card (visible only when logged in)

### WS-5: Price Alerts
**Specification:**
- Alert creation form: select coin, set target price, choose direction (above/below)
- Background check: run after each eBay data refresh — check if any alert conditions met
- Email notification: use SMTP or SendGrid API for alerts
- Store alerts in JSON file
- Rate-limit: max 10 alerts per user

---

## 5. Timeline to First Revenue

| Milestone | Target Date | Revenue Impact |
|-----------|-------------|----------------|
| Affiliate links live | Week 1, Day 1 | First commission in ~60 days (EPN payment lag) |
| AdSense live | Week 1, Day 2 | $2-5/mo immediately |
| Analytics installed | Week 1, Day 3 | No direct revenue, data for optimization |
| Email capture live | Week 2, Day 1 | List building — future monetisation |
| Portfolio tracker | Week 3 | User stickiness |
| Price alerts | Week 4 | Premium hook |
| First affiliate payout | ~Week 10-12 | ~$15-30 expected |
| First dealer sponsorship | Week 6-8 | $50-100/mo |

---

## 6. Decisions Needed from CEO

1. **eBay Partner Network signup** — Need James to create an EPN account (requires eBay account)
2. **Google AdSense** — Need approval (requires site review)
3. **Plausible vs Umami** — Preference for analytics provider
4. **OAuth provider** — Google-only or Google + GitHub?
5. **Pricing for premium** — $5/mo vs $10/mo? Free trial?
6. **Newsletter frequency** — Weekly, bi-weekly, or on new coin releases only?
7. **Dealer sponsorship pricing** — $50, $100, or $200/mo for featured placement?
8. **Data refresh cost budget** — RapidAPI credits vs direct eBay API
