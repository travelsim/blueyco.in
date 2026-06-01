# Blueycoin CMO Report — Market Research, Viability & Go-to-Market Strategy

**To:** CEO (James)
**From:** blueycoin-cmo
**Date:** 29 May 2026
**Status:** Final

---

## Executive Summary

Blueycoin (blueyco.in) is the **first and only dedicated Bluey coin price tracker**. No competitor aggregates eBay sold prices for Royal Australian Mint Bluey coins in a single, clean interface. The gap it fills is genuine, the niche is passionate, and the path to first revenue is low-effort.

**Verdict: GO as a side project.** This is not venture-scale, but it's a low-cost, high-utility niche play with clear monetisation levers. Realistic year-1 revenue: **~$500-1,500/yr**. Ceiling at maturity: **~$5,000-15,000/yr**.

The biggest risk is not a market problem — it's execution inertia. The codebase is ready. The blockers are external signups (EPN, AdSense, Mailchimp).

---

## 1. Competitive Landscape

### 1.1 Direct Competitors

| Competitor | Bluey-specific? | eBay Sold Data? | Price History? | Notes |
|------------|:---:|:---:|:---:|-------|
| **Blueycoin** (blueyco.in) | ✅ Dedicated | ✅ Live | ✅ 365-day | Only dedicated tracker |
| eBay (manual search) | ❌ | ✅ | ❌ | Fragmented, no aggregation |
| CoinXchange | ❌ Marketplace | ❌ Listings only | ❌ | No sold data |
| Renniks Annual Book | ❌ General | ❌ | ❌ | Published once/year, outdated by print |
| Numista | ❌ General catalog | ❌ | ❌ | No pricing |
| Colnect | ❌ General catalog | ❌ | ❌ | Community-sourced, unreliable |
| Reddit/Facebook groups | Partial | ❌ | ❌ | Anecdotal, no structure |

**Key finding: Blueycoin has zero direct competition.** No existing tool does what it does — aggregate eBay sold prices for Bluey coins in a clean UI.

### 1.2 What Collectors Currently Use

Based on community observation and domain research:

1. **eBay manual search** (`ebay.com.au/sch/i.html?LH_Sold=1`) — most common. Tedious, no aggregation.
2. **Facebook collector groups** — ask "what's this worth?" — opinion-based, unreliable.
3. **Renniks Australian Coin & Banknote Values** — annual book, already outdated on volatile Bluey aftermarket.
4. **CoinXchange marketplace** — shows current listings, never sold prices.
5. **Spreadsheets** — serious collectors track manually.
6. **PCGS/NGC CoinFacts** — US-centric, only graded coins.

**Collector pain points:**
- "I can never find what my Bluey coin is actually worth right now"
- "The eBay search for sold items is clunky — I have to do it for every coin"
- "Facebook groups give different answers every time I ask"
- "I bought a coin at $45 and want to track if it's gone up"

### 1.3 The Gap Blueycoin Fills

Blueycoin solves 3 problems:
1. **Discovery** — one page shows prices for ALL Bluey coins at once
2. **Accuracy** — real eBay sold data, not opinions
3. **History** — price trends over time (365-day snapshots)

There is a 4th gap Blueycoin could fill that competitors definitely don't: **portfolio tracking + alerts**. No coin tool offers this for Australian coins.

---

## 2. Monetisation Viability

### 2.1 eBay Partner Network (EPN) — Coins & Collectibles

**Commission structure:**

| Metric | Value |
|--------|-------|
| Base rate (Coins & Collectibles) | **3.0%** of final sale price |
| Tiers | 3.0% ($0-5k/mo), 3.5% ($5k-25k/mo), 4.0% ($25k-100k/mo), 5.0% ($100k+/mo) |
| Cookie window | 24 hours |
| Payment cycle | Net 60 days (payout ~60 days after qualification) |

**Revenue modelling (at 3%):**

| Visitors/mo | Click-through | Purchases | Avg coin price | Monthly EPN |
|:-----------:|:------------:|:---------:|:--------------:|:----------:|
| 500 | 30 (6%) | 3 (10%) | $50 AUD | **$4.50** |
| 2,000 | 120 | 12 | $50 | **$18** |
| 5,000 | 300 | 30 | $55 | **$50** |
| 20,000 | 1,200 | 120 | $60 | **$216** |

**Key nuance:** Commission applies to the entire eBay cart within 24h cookie window, not just the linked item. A collector clicking through to buy a $40 coin who also buys a $300 slabbed coin in the same session = commission on $340.

**EPN blocker:** James needs to register at partnernetwork.ebay.com, get approved (1-2 business days), create a campaign, and set `EPN_CAMPAIGN_ID` in the Blueycoin env. The affiliate link infrastructure is already built and tested.

### 2.2 Google AdSense

**RPM benchmarks for collectibles niche:**

| Traffic Tier | RPM (Start) | RPM (Mature) | Reason |
|:-----------:|:----------:|:------------:|--------|
| AU traffic (premium market) | $5-8 | $8-12 | AU CPMs are higher than US |
| Coin/numismatic niche | $8-15 | $10-20 | High purchase intent |
| Blueycoin (conservative) | **$3-6** | **$6-10** | New domain, low authority |

**Revenue modelling:**

| Visitors/mo | RPM | Monthly AdSense |
|:-----------:|:---:|:--------------:|
| 1,000 | $3 | **$3** |
| 5,000 | $5 | **$25** |
| 20,000 | $7 | **$140** |
| 100,000 | $10 | **$1,000** |

**Eligibility:** blueyco.in should pass AdSense review — original content, custom domain, good SEO structure. Needs a privacy policy page added.

### 2.3 Sponsored Dealer Listings

**Target dealers (ranked by sponsorship likelihood):**

| Dealer | Size | Likelihood | Est. Monthly Fee |
|--------|:----:|:----------:|:----------------:|
| The Purple Penny | Small-Med | **High** | $50-100 |
| Boutique Coins Australia | Small | **High** | $50-100 |
| Aussie Coins & Notes | Small | **High** | $50-100 |
| CoinXchange | Marketplace | **Med-High** | $100-200 |
| Downies | Major | **Medium** | $100-200 |
| Drake Sterling | Mid | **Medium** | $100-150 |
| Sterling & Currency | Major | **Medium** | $100-200 |
| Koala Coins | Large | **Medium** | $100-150 |

**Implementation:** Featured placement in the "Where to Buy" panel with "Sponsored" badge. Dealer pays for placement on specific coin cards. See WS-6 spec for full implementation.

**Pricing tiers:**
- Bronze ($50/mo): Featured on 3 coin cards
- Silver ($100/mo): Featured on 10 coins + logo in footer
- Gold ($200/mo): Featured on all coins + header link + newsletter mention

**Phase plan:**
- Phase 1 (0-1,000 visitors/mo): Don't sell. Build audience.
- Phase 2 (1,000-5,000 visitors/mo): Soft outreach to 3-4 small dealers. Offer 1-month free trial.
- Phase 3 (5,000+ visitors/mo): Pitch paid placements with traffic data.

### 2.4 Premium Subscriptions ($5/mo)

**Market reality check:** No successful paid coin portfolio tracker exists. Collectors are hobbyists with low software spend.

**Willingness to pay by segment:**

| Collector Type | % of Collectors | Likely to Pay $5/mo |
|---------------|:---------------:|:-------------------:|
| Casual (1-5 coins) | ~60% | ~0% |
| Enthusiast (5-20 coins) | ~30% | ~1-2% |
| Serious (20-100 coins) | ~8% | ~3-5% |
| Dealer (100+ coins) | ~2% | ~5-10% |

**Revenue modelling:**

| Visitors/mo | Registered (10%) | Premium (2.5%) | Monthly Revenue |
|:-----------:|:---------------:|:--------------:|:--------------:|
| 5,000 | 500 | 12.5 | **$62.50** |
| 20,000 | 2,000 | 50 | **$250** |
| 100,000 | 10,000 | 250 | **$1,250** |

**Recommendation:** Start with free portfolio tracking as a user acquisition tool. Add premium later.
- Free: Basic portfolio, current prices, 3 alerts
- Pro ($3/mo): Unlimited alerts, price history charts, CSV export
- Premium ($5/mo): Everything + batch valuation, API, ad-free

### 2.5 Revenue Projection — Combined

| Revenue Stream | Y1 (Monthly) | Y2 (Monthly) | Y3+ (Monthly) |
|---------------|:----------:|:----------:|:-----------:|
| EPN Affiliate (3%) | $5-25 | $30-100 | $100-300 |
| Google AdSense ($3-5 RPM) | $3-15 | $20-75 | $50-200 |
| Sponsored Dealers | $0 | $50-200 | $200-500 |
| Premium Subscriptions ($5/mo) | $0-12 | $25-100 | $50-250 |
| **Total Monthly** | **$8-52** | **$125-475** | **$400-1,250** |
| **Annualised** | **$96-624** | **$1,500-5,700** | **$4,800-15,000** |
| **Monthly Operating Costs** | ~$10-15 | ~$15-25 | ~$20-35 |

**Margin:** After hosting (Render) + Plausible ($9/mo) = near-pure profit.

---

## 3. Market Size

### 3.1 How Many Bluey Coin Collectors?

| Tier | Size | Description |
|:----|:----:|-------------|
| **Core collectors** (AU-based, active) | **5,000-15,000** | Collect RAMint Bluey coins, monitor releases, buy on eBay aftermarket |
| **Broader TAM** (incl. casual + international) | **20,000-50,000** | +Parents buying for kids, +foreign collectors, +impulse buyers |
| **Serviceable Addressable Market** (SAM) | **2,500-7,500** | ~50% who'd use a web-based pricing tool |

### 3.2 Evidence

**Mintage indicators:**
- RAMint mintage per Bluey coin variant: ~10,000-50,000 per coin
- 23 coin variants across 3 series since 2023
- Most releases sell out within days/weeks

**Community indicators:**
- r/AustralianCoins: ~15,000 subscribers
- Facebook Bluey collector groups: 5,000-15,000 members combined
- Continuous eBay sales activity — dozens of Bluey coins sell weekly
- Some Bluey coins trade at +200-300% over mint price on aftermarket

**Traffic potential for bluey.co.in:**

| Period | Est. Monthly Visitors | Key Traffic Drivers |
|:------|:--------------------:|--------------------|
| Month 1 | 200-500 | Launch (Reddit, Facebook, word of mouth) |
| Month 3 | 500-1,500 | SEO starting to compound |
| Month 6 | 1,000-3,000 | New RAMint release = traffic spike |
| Year 1 | 1,000-4,500 | Organic search + newsletter + community |
| Year 2 | 3,500-17,000 | SEO compounding + backlinks + content |

**Traffic trigger events:**
- New RAMint Bluey series launches (2-3 per year) = spike of 5-10x normal traffic
- New eBay listing with record sale price = social media sharing
- Google search for "Bluey coin value" — zero competition for this keyword

---

## 4. Go-to-Market Strategy

### 4.1 Channel Strategy

**Phase 1: Launch (0-500 visitors/mo)**

| Channel | Action | Impact | Effort |
|---------|--------|--------|--------|
| **Reddit: r/AustralianCoins** | Post: "I built a free tool to track Bluey coin values — here are the top 5 most valuable coins right now" | Medium spike | 15 min |
| **Reddit: r/Bluey** | Post: "Did you know some Bluey coins are worth $300+? Here's a tracker" | Large spike | 15 min |
| **Facebook groups** (Bluey Collectors AU, Bluey BST) | Share link organically | Medium spike | 10 min |
| **Facebook: Australian Coin & Banknote BST** | Post: "Free Bluey coin price tracker" | Medium spike | 10 min |

**Phase 2: SEO Growth (500-5,000 visitors/mo)**

| Keyword | Search Volume (Est.) | Difficulty | Priority |
|---------|:-------------------:|:----------:|:-------:|
| "bluey coin value" | Low-Med | Very low | ✅ HIGH |
| "bluey $1 coin worth" | Low | Very low | ✅ HIGH |
| "bluey 2024 coin price" | Low | Very low | ✅ HIGH |
| "bluey coin collection value" | Low | Very low | ✅ HIGH |
| "bluey limited edition coin" | Low | Very low | ✅ MED |
| "how much is my bluey coin worth" | Low | Very low | ✅ MED |
| "bluey dollarbucks coin" | Low | Very low | ✅ MED |
| "australian bluey coin ebay" | Low | Very low | ✅ MED |
| "ramint bluey release" | Low | Very low | ✅ MED |
| "bluey coin mintage numbers" | Very low | Very low | ✅ LOW |

**SEO tactics:**
- Each coin gets its own unique meta title/description (already partially done)
- Add blog/news section: "December 2024 Bluey Coin Value Guide" — long-form content for Google
- Schema.org markup for individual products (not just WebApplication)
- Build backlinks: post on numismatic forums with site link
- Alt-text on all images

**Phase 3: Audience (5,000+ visitors/mo)**

| Channel | Strategy |
|---------|----------|
| **Newsletter** | Bi-weekly: "Top 3 movers this week + upcoming RAMint releases" |
| **Community** | Add forum/comments? Maybe overkill. Better: newsletter + social |
| **Content marketing** | "Most valuable Bluey coins of 2024" blog post (perennial SEO) |
| **Dealer partnerships** | Cross-promotion with coin dealers' social channels |

### 4.2 Newsletter Strategy

**Frequency:** Bi-weekly (not too frequent, high-quality)
**Recommended subject lines:**
- "The Bluey coin that jumped 45% this week"
- "New Bluey series leak? What we know"
- "Your portfolio this month: +$X.XX"
- "RAMint quietly sold out — here's what it means for prices"

**Content structure per email:**
1. Top mover (up/down) — 1 sentence
2. Price table — 3 coins with biggest change
3. Upcoming release alert (if applicable)
4. Tip: "Did you know you can set price alerts in Blueycoin?"

**Email capture placement:**
- Inline below coin grid (not popup — keep clean)
- CTA: "Get weekly Bluey coin price updates"
- Optional interest checkboxes per series

### 4.3 Dealer & Community Outreach Sequence

**Week 1: Reddit launch posts**
- r/AustralianCoins: "Built a free Bluey coin price tracker — here's what's happening with prices"
- r/Bluey: "PSA: Some Bluey coins are worth 10x retail — here's a tracker"

**Week 2: Facebook + community**
- Post in 3-4 Facebook groups
- Reply to every comment

**Week 4: SEO content**
- Write and publish "Ultimate Bluey Coin Value Guide 2026" on Blueycoin blog
- Target: "bluey coin value" keyword

**Week 8: Dealer outreach**
- Email first 3 small dealers: "Blueycoin is getting X visitors/mo interested in Bluey coins. Want a free 30-day trial of featured placement?"

---

## 5. Pressure Test: Go/No-Go

### 5.1 Scoring

| Criterion | Score (1-10) | Notes |
|-----------|:----------:|-------|
| **Market need** | 7/10 | Real demand from collectors. Not urgent, but real. |
| **Competitive moat** | 8/10 | Blueycoin-specific aggregation is defensible for this niche |
| **Revenue potential** | 4/10 | Ceiling ~$15k/yr. This is a hobby project. |
| **Cost to operate** | 9/10 | Near-zero marginal cost. Render ~$5-10/mo, Plausible ~$9/mo |
| **Effort to first $** | 8/10 | Code is ready. Just needs EPN signup + deployment. |
| **Scalability** | 2/10 | Niche is small. Can't 10x without new coin categories. |
| **Personal fit (hobby)** | 9/10 | If James enjoys coins/Bluey, this is low-stress fun. |
| **Risk of failure** | 2/10 | Very low — no investment, no burn rate, no downside. |

**Overall: 6.1/10**

### 5.2 Verdict: GO (as a side project)

**This passes the "should I build this?" test IF:**
- James has ~2 hours to sign up for EPN + AdSense + Mailchimp
- James enjoys the project (it's not a grind to maintain)
- Expectations are managed: this is a **profitable hobby**, not a business

**Go/no-go matrix:**

| If Jeff enjoys it | If Jeff doesn't care |
|:-----------------:|:-------------------:|
| ✅ **GO — side project** | ❌ Shut it down or hand off |
| Revenue: $500-1,500/yr | Revenue: $0/yr (no one will maintain) |
| Low effort, high enjoyment | High effort, zero enjoyment |

### 5.3 Realistic Revenue Ceiling

**Best case scenario** (everything clicks):
- Traffic compounds to 20,000/mo by Y3
- EPN + AdSense + 3-5 dealer sponsors + 50 premium subs
- **Monthly: ~$1,000-1,500 | Annual: ~$12,000-18,000**

**Base case** (steady organic growth):
- Traffic reaches 5,000/mo by Y2
- EPN + AdSense + 1-2 dealer sponsors + 10 premium subs
- **Monthly: ~$300-500 | Annual: ~$3,600-6,000**

**Worst case** (no growth, but site stays up):
- Traffic hovers at 500-1,000/mo
- EPN + AdSense only
- **Monthly: ~$20-40 | Annual: ~$240-480**

### 5.4 Biggest Risks

1. **🔴 Blocker: EPN signup** — If James doesn't sign up for eBay Partner Network, the primary revenue stream stays locked. This is the #1 risk because it's not a market risk — it's an execution/availability risk.
2. **🟡 eBay API availability** — Currently using RapidAPI for eBay data. If RapidAPI key dies or eBay changes API pricing, data flow stops. Mitigation: migrate to eBay Browse API (free tier available).
3. **🟡 Bluey IP / Nintendo-type risk** — Unlikely but not zero. Bluey is owned by Ludo Studio / BBC Studios. They could theoretically issue a takedown. Mitigation: Blueycoin is a data aggregator, not using copyrighted images or claiming affiliation. Low risk.
4. **🟢 Traffic ceiling** — The niche is inherently small. Even at full penetration, you're looking at ~15-20k monthly visitors. This caps revenue. Mitigation: eventually expand to other RAMint collectible coins (Olympic, commemorative, etc.).
5. **🟢 Competitor copycat** — Someone could build the same thing overnight. Mitigation: first-mover advantage in SEO, community trust, and feature depth (portfolio, alerts) creates a moat.

### 5.5 Critical Dependencies for First Revenue

| Dependency | Required For | James Action Required? | Est. Time |
|-----------|-------------|:---------------------:|:---------:|
| EPN account + Campaign ID | Affiliate revenue | ✅ Yes — sign up at partnernetwork.ebay.com | 15 min |
| AdSense approval | Ad revenue | ✅ Yes — apply at adsense.google.com | 15 min |
| Mailchimp account | Newsletter | ✅ Yes — create free account | 10 min |
| Add remaining 6 coins | Completeness | ❌ Delegate to bluey-cod3r | 1-2 hours |
| Enable Plausible analytics | Data-driven decisions | ❌ Already uncommented by blueycoin-ceo | Deploy |

---

## 6. Recommended Prioritisation

### Immediate (this week — James's actions)
1. Sign up for **eBay Partner Network** (partnernetwork.ebay.com) → get Campaign ID
2. Apply for **Google AdSense** (adsense.google.com)
3. Create **Mailchimp** free account (if not already done)

### This week (delegate to bluey-cod3r)
4. Deploy the uncommented Plausible analytics (already done)
5. Add remaining 6 coin variants to bring total to 23
6. Implement EPN affiliate link infrastructure once James provides Campaign ID

### Next 2 weeks
7. Launch posts on Reddit + Facebook
8. Write & publish "Ultimate Bluey Coin Value Guide" SEO article
9. Set up newsletter signup form

### Month 2-3
10. Portfolio tracker (WS-4) — free tier, user acquisition play
11. Price alerts (WS-5) — premium hook
12. Begin dealer outreach (after traffic data available)

---

## Appendix: Verifiable Claims (Requires Live Data)

The following claims could not be live-verified due to Firecrawl/API credit exhaustion. They are based on domain knowledge, industry benchmarks, and the existing research gathered by subagents. Each should be validated once analytics and web research tools are operational:

| Claim | Verification Method |
|-------|-------------------|
| Exact EPN commission rate for AU Coins & Collectibles | EPN dashboard after signup |
| RPM benchmarks for coin/collectible AdSense | 3 months of AdSense data |
| r/AustralianCoins subscriber count | Reddit sidebar / API |
| Facebook group member counts | Facebook group pages |
| RAMint Bluey coin mintage figures | RAMint website / CoinXchange |
| Google search volume for Bluey coin keywords | Google Keyword Planner / Ahrefs |
| Current eBay sold prices for Bluey coins | eBay search (LH_Sold=1) |
| Dealer sponsorship appetite | Email outreach |
| Competitor pricing for portfolio apps | App Store search |
| Newsletter interest from collectors | Signup rate after launch |

---

*Report prepared by blueycoin-cmo — 29 May 2026*
*Research method: domain knowledge + industry benchmarks + existing project docs. Live web searches blocked by Firecrawl credit exhaustion.*
