# WS-4: User Accounts + Portfolio Tracker — cod3r spec

## Goal
Add user accounts and portfolio tracking. Core stickiness feature — users can track their collection value over time.

## 1. User Accounts (OAuth)

### Implementation
Keep it simple — no password storage, no email/password auth. Use OAuth only.

```python
# Add to server.py dependencies
import secrets
import hashlib
import urllib.parse
from http.cookies import SimpleCookie

# In-memory session store (or JSON file for persistence)
SESSIONS_FILE = 'sessions.json'
USERS_FILE = 'users.json'

# Google OAuth config
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
OAUTH_REDIRECT_URI = 'https://blueyco.in/api/auth/callback'
```

### Endpoints

**GET /api/auth/login** — Redirect to Google OAuth:
```python
def do_GET(self):
    if self.path == '/api/auth/login':
        params = urllib.parse.urlencode({
            'client_id': GOOGLE_CLIENT_ID,
            'redirect_uri': OAUTH_REDIRECT_URI,
            'response_type': 'code',
            'scope': 'openid email profile',
            'state': secrets.token_urlsafe(16),
        })
        self.send_response(302)
        self.send_header('Location', f'https://accounts.google.com/o/oauth2/auth?{params}')
        self.end_headers()
```

**GET /api/auth/callback** — Handle OAuth callback, create session:
- Exchange `code` for access token
- Fetch user info from Google (email, name, picture)
- Generate session token, store in SESSIONS_FILE
- Set cookie: `Set-Cookie: session={token}; HttpOnly; SameSite=Lax; Max-Age=86400*30`
- Redirect to `/`

**POST /api/auth/logout** — Clear session cookie, delete session

**Middleware**: Check for session cookie on every API request, attach `user_id` to context.

### Frontend (index.html)
- Add "Sign in with Google" button in header
- Replace with user avatar + dropdown (Portfolio, Sign out) when logged in
- Minimal CSS: Google sign-in button styling

## 2. Portfolio Tracker

### Data Model (users.json)
```json
{
  "user_abc123": {
    "email": "user@gmail.com",
    "name": "User Name",
    "picture": "https://...",
    "created_at": 1716800000,
    "portfolio": [
      {
        "coin_id": "s3_proof_silv",
        "quantity": 2,
        "purchase_price": 115,
        "purchase_date": "2026-03-15",
        "note": "Gift for mum"
      }
    ]
  }
}
```

### Endpoints

**GET /api/portfolio** — Returns user's portfolio with current market values:
```python
def do_GET(self):
    if self.path == '/api/portfolio':
        user_id = get_session_user(self)
        if not user_id:
            self._json(401, {'error': 'Not authenticated'})
            return
        user = load_user(user_id)
        portfolio = []
        for item in user.get('portfolio', []):
            coin = COIN_BY_ID.get(item['coin_id'])
            current_data = _cache.get(item['coin_id'], {}).get('ebay', {})
            current_value = current_data.get('average_price') or 0
            total_cost = item['quantity'] * item['purchase_price']
            total_value = item['quantity'] * current_value
            portfolio.append({
                **item,
                'coin_name': coin['name'] if coin else 'Unknown',
                'current_price': current_value,
                'total_cost': total_cost,
                'total_value': total_value,
                'profit_loss': total_value - total_cost,
                'profit_loss_pct': ((total_value - total_cost) / total_cost * 100) if total_cost else 0,
            })
        self._json(200, {
            'portfolio': portfolio,
            'total_value': sum(p['total_value'] for p in portfolio),
            'total_cost': sum(p['total_cost'] for p in portfolio),
            'total_pl': sum(p['profit_loss'] for p in portfolio),
        })
```

**POST /api/portfolio/add** — Add coin to portfolio

**POST /api/portfolio/remove** — Remove coin from portfolio

### Frontend
- Portfolio page (shown when logged in): `/portfolio` or modal
- Summary cards: Total Value, Total Cost, P&L (absolute + %)
- Per-coin table: Name, Qty, Purchase Price, Current Price, Value, P&L
- "Add to Portfolio" button on each coin card (opens small form: qty, price, date)
- Portfolio value chart over time (reuse Chart.js)

### Storage Consideration
For simplicity, use JSON files (already the pattern — `ebay_cache.json`, `price_history.json`).
If portfolio + user data grows beyond ~1000 users, migrate to SQLite.
