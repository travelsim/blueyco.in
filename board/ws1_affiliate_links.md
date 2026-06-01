# WS-1: Affiliate Links Implementation — cod3r spec

## Goal
Convert ALL existing eBay AU links in Blueycoin to eBay Partner Network (EPN) affiliate-tracked links. This is the single highest-ROI quick win.

## Prerequisites
- James needs to sign up for eBay Partner Network at https://partnernetwork.ebay.com/ (uses his eBay account)
- Get Campaign ID and Custom Tracking ID from EPN dashboard

## Technical Implementation

### 1. Server-side URL transformation
Add a function in `server.py`:

```python
EPN_CAMPAIGN_ID = os.environ.get('EPN_CAMPAIGN_ID', '')
EPN_TRACKING_ID = 'blueycoin'

def affiliate_url(raw_url: str, coin_id: str = '', source: str = 'ebay') -> str:
    """Wrap an eBay AU URL with EPN affiliate tracking parameters."""
    if not raw_url or not raw_url.startswith('https://www.ebay.com.au'):
        return raw_url  # only transform eBay AU links
    if not EPN_CAMPAIGN_ID:
        return raw_url  # no campaign configured, return raw
    
    custom_id = f'blueycoin-{source}-{coin_id}' if coin_id else 'blueycoin'
    separator = '&' if '?' in raw_url else '?'
    return f"{raw_url}{separator}mkrid=705-53470-19255-0&siteid=15&campid={EPN_CAMPAIGN_ID}&customid={custom_id}&toolid=10001&mkevt=1"
```

### 2. Where to apply affiliate links

**A. Buy panel eBay AU listings** (`_ebay_live_options` in server.py)
- Transform the `url` field of each eBay option before returning in API response
- Add `source='ebay_buy'` + `coin_id`

**B. Recent sale "↗" view-on-eBay links** (frontend, index.html)
- In `buildCard()` function, the `<a class="view-ebay">` links from `p.link`
- Either: add `data-affiliate="true"` attribute and transform client-side
- Or better: add a new endpoint `GET /api/redirect?url=...` that 302-redirects through EPN
- Or simplest: the server could add a new field `affiliate_link` per product in `/api/prices`

**C. Hard-coded eBay AU fallback URLs**
- In `COINS` catalogue: some have `cxUrl` pointing to eBay
- The "Where to Buy" eBay AU search link fallback

**Recommended approach**: Add an `POST /api/affiliate-redirect` endpoint that returns the EPN-wrapped URL. The frontend calls this when any eBay link is clicked. This keeps the campaign ID server-side (more secure, compliant).

### 3. Compliance
- Add `rel="sponsored noopener noreferrer"` to all affiliate links
- Add a small disclosure text in the footer: "Some links on this site are affiliate links. We may earn a commission if you make a purchase through these links."
- EPN requires links to be clicked within 24h of eBay session for commission qualification

### 4. CoinXchange & Other Retailers
- Investigate CoinXchange affiliate program (email partner@coinxchange.com.au)
- RAMint (eshop.ramint.gov.au) — government mint, unlikely to offer affiliate
- Australia Post — may have a partner program
- If no affiliate program exists, leave links as-is

## Testing
- Click each transformed link → verify it redirects through EPN
- Verify EPN dashboard registers clicks
- Test with `customid` parameter to track per-coin performance
- Verify disclosure text is visible
