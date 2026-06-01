# WS-6: Revenue Optimization — cod3r spec

## Goal
Implement additional revenue streams alongside affiliate links.

## 1. Google AdSense

### Placement
Non-intrusive ad units:
- **Below the coin grid** (before footer) — horizontal banner, 728×90
- **Between series tabs and coin grid** — small rectangle, 300×250 (mobile friendly)
- **Footer** — 468×60 banner

### Implementation
```html
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"></script>
<!-- Blueycoin responsive ad -->
<ins class="adsbygoogle"
     style="display:block"
     data-ad-client="ca-pub-XXXXXXXXXXXXXX"
     data-ad-slot="XXXXXXXXXX"
     data-ad-format="auto"
     data-full-width-responsive="true"></ins>
<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>
```

### CSP Update
Add `https://pagead2.googlesyndication.com` and `https://googleads.g.doubleclick.net` to `script-src`, `connect-src`, and `img-src`.

### Priority
Medium. AdSense requires application + approval. RPM on niche content sites is $3-10.
With 200-500 daily visitors: $0.60-5.00/day. Not huge but passive.

## 2. Sponsored Dealer Listings

### Concept
Coin dealers pay for featured placement in the "Where to Buy" panel. E.g.:
- "Featured Dealer" slot at the top of the buy panel
- Different background color to distinguish from organic results
- Disclosure: "Sponsored" label

### Implementation

**Data model** (retailer_prices.json or new file sponsored_dealers.json):
```json
{
  "active_sponsors": [
    {
      "dealer_id": "aussie_coins",
      "name": "Aussie Coins & Collectibles",
      "url": "https://aussiecoins.com.au/search?q={q}",
      "logo_url": "",
      "start_date": "2026-06-01",
      "end_date": "2026-07-01",
      "monthly_fee": 100,
      "coins": ["s1_bluey", "s1_bingo", "s3_proof_silv"]
    }
  ]
}
```

**Backend**: Add sponsored results to buy-options response:
```python
def get_sponsored_options(keywords, coin_id):
    """Check if any active sponsors cover this coin."""
    sponsors = load_sponsors()
    results = []
    for s in sponsors:
        if coin_id in s.get('coins', []) or not s.get('coins'):
            results.append({
                'retailer_id': f"sponsored_{s['dealer_id']}",
                'name': f"⭐ Featured: {s['name']}",
                'price': None,
                'available': True,
                'url': s['url'].replace('{q}', urllib.parse.quote(keywords)),
                'link_only': True,
                'is_sponsored': True,
            })
    return results[:2]
```

**Frontend**: In `renderBuyOptions()`, style sponsored items with a "Sponsored" badge.

**Pricing to dealers**: $50-200/mo per slot. Proposed tiers:
- Bronze ($50/mo): Featured in buy panel for 3 coins
- Silver ($100/mo): Featured for 10 coins + logo in footer
- Gold ($200/mo): Featured for all coins + header link + newsletter mention

### Outreach
- Identify AU coin dealers: Downies, Sterling & Currency, Australian Coin Centre, etc.
- Reach out with traffic stats (after analytics is installed)
- Offer 1-month free trial to first 3 dealers

## 3. Premium Tier ($5-10/mo)

### Features
| Feature | Free | Premium ($5/mo) |
|---------|------|------------------|
| Coin prices | ✅ | ✅ |
| Search/filter | ✅ | ✅ |
| Portfolio (up to 10 coins) | ✅ | ✅ (unlimited) |
| Price alerts (up to 3) | ✅ | ✅ (unlimited) |
| Price history (7 days) | ✅ | ✅ (5 years) |
| Email alerts | ✅ | ✅ (SMS/Telegram too) |
| Export portfolio | ❌ | ✅ (CSV/PDF) |
| Early access to data | ❌ | ✅ (data refresh 2x faster) |
| No ads | ❌ | ✅ |

### Payment Integration
- Use Stripe (easiest) or LemonSqueezy
- Webhook endpoint: `POST /api/stripe/webhook`
- Track subscription status per user in users.json

### Implementation Priority
LOW. Only implement after WS-4 (portfolio) and WS-5 (alerts) are live and proven.

## 4. Referral Program
- Users get a referral link
- Referring a friend who signs up = 1 month free premium
- Word-of-mouth growth for free
- Implement simple: `?ref=user_id` cookie tracking
