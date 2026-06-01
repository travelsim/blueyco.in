# WS-3: Technical Improvements — cod3r spec

## Goals
Improve data freshness, usability (search/filter/sort), and data persistence.

## 1. Dynamic Refresh Frequency

### Current
- 14-day hard-coded REFRESH_SECS for all coins
- 24h CHECK_SECS to check if refresh needed

### Proposed
Adaptive refresh based on trading volume:

```python
def refresh_interval(coin_id, cache_entry):
    """Return seconds until next refresh based on coin activity."""
    if not cache_entry or not cache_entry.get('results'):
        return 7 * 24 * 3600  # no sales data — refresh weekly
    sales_count = cache_entry.get('results', 0)
    if sales_count >= 10:
        return 6 * 3600       # high volume — every 6 hours
    elif sales_count >= 3:
        return 24 * 3600      # medium volume — daily
    else:
        return 7 * 24 * 3600  # low volume — weekly
```

## 2. Search Bar

Add a real-time search input at the top of the page (above the series tabs):

```html
<input type="text" id="search-input" placeholder="🔍 Search coins by name, year, or mintage..." autocomplete="off">
```

Client-side JavaScript:
```javascript
const searchInput = document.getElementById('search-input');
searchInput.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase().trim();
    if (!query) { activeFilter = null; renderGrid(); return; }
    activeFilter = (coin) => 
        coin.name.toLowerCase().includes(query) ||
        String(coin.year).includes(query) ||
        (coin.mintage && coin.mintage.toLowerCase().includes(query)) ||
        coin.denomination.includes(query);
    renderGrid();
});
```

Modify `renderGrid()` to respect `activeFilter` (in addition to `activeSeries`).

## 3. Sort Dropdown

Add sort selector next to search bar:

```html
<select id="sort-select">
    <option value="default">Default order</option>
    <option value="premium_desc">Highest Premium</option>
    <option value="price_desc">Highest eBay Avg</option>
    <option value="price_asc">Lowest eBay Avg</option>
    <option value="mintage_asc">Rarest (low mintage)</option>
    <option value="newest">Newest first</option>
</select>
```

Sort function:
```javascript
function sortCoins(coins) {
    const sort = document.getElementById('sort-select').value;
    if (sort === 'default') return coins;
    return [...coins].sort((a, b) => {
        const aData = coinData[a.id]?.ebay;
        const bData = coinData[b.id]?.ebay;
        switch(sort) {
            case 'premium_desc':
                return (calcPremium(bData?.average_price, b.mintPrice) || 0) -
                       (calcPremium(aData?.average_price, a.mintPrice) || 0);
            case 'price_desc':
                return (parseFloat(bData?.average_price) || 0) - 
                       (parseFloat(aData?.average_price) || 0);
            case 'price_asc':
                return (parseFloat(aData?.average_price) || Infinity) - 
                       (parseFloat(bData?.average_price) || Infinity);
            case 'mintage_asc':
                return (parseMintage(a.mintage) || Infinity) - 
                       (parseMintage(b.mintage) || Infinity);
            case 'newest':
                return b.year - a.year;
            default: return 0;
        }
    });
}
```

## 4. Price History Persistence

### Current
Mini charts use eBay products data from the latest fetch — no historical view beyond current batch.

### Proposed
Store daily snapshots:

```python
PRICE_HISTORY_FILE = 'price_history.json'

def _save_price_snapshot():
    """Called after each eBay refresh cycle. Appends today's avg prices."""
    today = datetime.now().strftime('%Y-%m-%d')
    snapshot = {}
    for coin in COINS:
        cid = coin['id']
        entry = _cache.get(cid, {}).get('ebay', {})
        snapshot[cid] = {
            'date': today,
            'avg_price': entry.get('average_price'),
            'sales_count': entry.get('results', 0),
            'min_price': entry.get('min_price'),
            'max_price': entry.get('max_price'),
        }
    
    try:
        with open(PRICE_HISTORY_FILE, 'r') as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = []
    
    # Avoid duplicate entries for same day
    history = [h for h in history if h.get('date') != today]
    history.append(snapshot)
    
    # Keep last 365 days
    history = sorted(history, key=lambda x: x['date'])[-365:]
    
    with open(PRICE_HISTORY_FILE, 'w') as f:
        json.dump(history, f)
```

Add endpoint `GET /api/price-history?coinId={id}&days=90` that returns the historical data for charting.

### Frontend Update
Update mini chart to use historical data when available, with a time range selector (1m, 3m, 6m, 1y, All).

## 5. eBay API Migration (Research)

### Current
- RapidAPI "eBay Average Selling Price" — unknown cost, may have limits
- RapidAPI "Real-Time eBay" — additional cost

### Option: Direct eBay Browse API
- eBay Developers Program: https://developer.ebay.com/
- Free tier: up to 500,000 calls/month for Browse API
- Need eBay developer account + application keys
- API: `GET https://api.ebay.com/buy/browse/v1/item_summary/search?q={query}&limit=50&filter=buyingOptions:{FIXED_PRICE|AUCTION}`

### Recommendation
Move to direct eBay API if current RapidAPI costs are significant. If RapidAPI is free/low-cost, keep it for now.
