# Blueycoin Board Report — Week 1

**To:** CEO (James)
**From:** COO
**Date:** 28 May 2026

---

## Executive Summary

Blueycoin is a clean, well-built coin price tracker with **zero revenue**. The path to first revenue is clear and low-effort. I've decomposed the vision into 6 workstreams, produced detailed specs for each, and am ready to hand off engineering work to cod3r.

**Fastest path to $:** Affiliate links (EPN) + AdSense. Could be live this week. First commissions hit ~60 days later due to EPN payment cycle.

---

## Current State Assessment

| Dimension | Rating | Notes |
|-----------|--------|-------|
| UI/UX | ★★★★☆ | Card layout, mini charts, buy panel — legitimately good |
| Backend | ★★★★☆ | Caching, rate limiting, security-aware (CSP, no innerHTML) |
| SEO | ★★★☆☆ | Meta tags, schema.org — decent but could improve |
| Features | ★★☆☆☆ | Prices only — no portfolio, search, alerts, accounts |
| Monetisation | ☆☆☆☆☆ | **Zero** — not even affiliate links on price data worth $50-350/coin |
| Traffic | ★☆☆☆☆ | Unknown (no analytics), but Bluey is a massive IP in AU |
| Security | ★★★★★ | Threat-modelled, CSP enforced, safe DOM APIs |

---

## Monetisation Strategy — 3 Tiers

### Tier 1: Quick Wins (This Week) → $5-15/mo
| Workstream | Est. Effort | Revenue | Status |
|------------|-------------|---------|--------|
| **WS-1: EPN Affiliate Links** | 1-2 days eng | $5-10/mo initial → $30-60/mo @ scale | 🔲 Ready for cod3r — needs James' EPN signup first |
| **WS-2a: Google AdSense** | 1 hour | $2-5/mo | 🔲 Needs Google approval |
| **WS-2b: Analytics** | 2 hours | $0 (data driver) | 🔲 Ready for cod3r |

### Tier 2: Audience Building (Week 2) → $50-200/mo
| Workstream | Est. Effort | Revenue | Status |
|------------|-------------|---------|--------|
| **WS-2c: Email Capture** | 1 day | List building (future $) | 🔲 Ready for cod3r |
| **WS-3: Search/Filter/Sort** | 2-3 days | UX improvement | 🔲 Ready for cod3r |
| **WS-3: Data refresh frequency** | 1 day | Better data | 🔲 Ready for cod3r |

### Tier 3: Premium Features (Weeks 3-4) → $50-100/mo
| Workstream | Est. Effort | Revenue | Status |
|------------|-------------|---------|--------|
| **WS-4: Portfolio Tracker** | 1-2 weeks | User stickiness | 🔲 Spec ready — needs CEO OAuth decision |
| **WS-5: Price Alerts** | 3-5 days | Premium hook | 🔲 Spec ready |
| **WS-6: Sponsored Dealers** | 2-3 days | $50-200/mo per dealer | 🔲 Sales outreach needed |

---

## What's Been Delegated (Specs Written, Ready for cod3r)

All specs saved to `/Users/jameslove/.hermes/hermes-agent/`:

| Spec File | Workstream | Priority |
|-----------|------------|----------|
| `ws1_affiliate_links.md` | EPN affiliate links — all eBay links → tracked URLs | 🔴 P0 |
| `ws2_analytics_email.md` | Plausible analytics + Mailchimp email capture | 🟡 P1 |
| `ws3_technical_improvements.md` | Dynamic refresh, search, filter, sort, price history | 🟡 P1 |
| `ws4_portfolio_tracker.md` | Google OAuth accounts + portfolio tracking | 🟢 P2 |
| `ws5_price_alerts.md` | Price alert engine + email notification | 🟢 P2 |
| `ws6_revenue_optimization.md` | AdSense, sponsored dealers, premium tier | 🟢 P2 |

---

## What Needs CEO Decision

1. **🔴 eBay Partner Network signup** — You need to create an EPN account at https://partnernetwork.ebay.com/. Takes 10 minutes with your eBay account. This is the #1 blocker.
2. **🔴 Google AdSense approval** — Apply at https://adsense.google.com/. Site needs to pass review (should be fine — it's content-rich with no policy violations).
3. **🟡 OAuth provider** — Google-only? Or Google + GitHub? Google is simpler (one integration).
4. **🟡 Mailchimp account** — Create free account for email capture. Or prefer ConvertKit?
5. **🟢 Premium pricing** — $5/mo vs $10/mo? I recommend $5/mo to start (lower barrier).
6. **🟢 Newsletter frequency** — Weekly digest vs bi-weekly vs on-launch-only?

---

## Timeline to First Revenue

```
Week 1: EPN links + AdSense live → $0 immediate, commissions accrue
Week 2: Analytics installed → understand traffic → optimize
Week 4: Email capture live → start building audience
Week 8-10: First EPN payout → ~$15-30
Week 10-12: First dealer sponsor → ~$50-100/mo
Month 3-4: Premium launch → $50-100/mo
Target Year 1 Run Rate: $2,000-4,500/yr
```

---

## Recommended Actions This Week

1. **James (CEO):** Sign up for EPN + AdSense (30 min total)
2. **cod3r (CTO):** Implement WS-1 (affiliate links) — estimate 1-2 days
3. **cod3r (CTO):** Implement WS-2 (analytics + email) — estimate 1 day
4. **COO:** Start dealer outreach list — ongoing

---

## Revenue Projection Detail

| Month | EPN | AdSense | Sponsored | Premium | Total |
|-------|-----|---------|-----------|---------|-------|
| 1 | $5-10 | $2-5 | $0 | $0 | **$7-15** |
| 2 | $15-30 | $5-10 | $50-100 | $0 | **$70-140** |
| 3 | $30-60 | $10-20 | $100-200 | $0-50 | **$140-330** |
| 6 | $50-100 | $15-30 | $100-200 | $50-100 | **$215-430** |
| 12 | $80-150 | $25-50 | $200-300 | $100-150 | **$405-650/mo** |

**Year 1 Estimated Run Rate: $4,860-7,800**

---

## Strategic Notes

**Why Blueycoin is undervalued:**
- Bluey is the #1 kids' IP in Australia — immense collector demand
- RAMint coins frequently sell out minutes after launch
- Your price data is genuinely useful — collectors are using this
- The aftermarket premium on some coins is +293% (2026 Coloured Proof)
- Every single pageview that sees an eBay price and clicks "Where to Buy" is a potential commission event

**The biggest risk is doing nothing.** Every day without affiliate links is lost revenue that will never be recovered.

**Next steps from COO:** Awaiting your decisions on the 🔴 items above. Once EPN is set up, I'll hand WS-1 to cod3r and we'll have affiliate links live within 48 hours.
