# WS-5: Price Alerts — cod3r spec

## Goal
Let users set price alerts on coins. Email notification when a coin hits the target price.

## Architecture

### Data Model (alerts.json)
```json
[
  {
    "id": "alert_001",
    "user_id": "user_abc123",
    "coin_id": "s3_proof_silv",
    "target_price": 300.00,
    "direction": "below",
    "notified": false,
    "created_at": 1716800000
  }
]
```

### Endpoints

**POST /api/alerts** — Create alert (requires auth):
```json
// Request
{ "coin_id": "s3_proof_silv", "target_price": 300, "direction": "below" }
// Response
{ "id": "alert_001", "status": "created" }
```

**GET /api/alerts** — List user's alerts (requires auth)

**DELETE /api/alerts/{id}** — Delete alert (requires auth)

### Alert Check Engine

Run after every eBay refresh cycle (`_refresh_worker`):

```python
def check_alerts():
    """After eBay data refresh, check all active alerts."""
    try:
        with open(ALERTS_FILE, 'r') as f:
            alerts = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return
    
    triggered = []
    for alert in alerts:
        if alert.get('notified'):
            continue
        coin_data = _cache.get(alert['coin_id'], {}).get('ebay', {})
        current_price = coin_data.get('average_price')
        if current_price is None:
            continue
        
        direction = alert.get('direction', 'below')
        target = alert['target_price']
        
        if (direction == 'below' and current_price <= target) or \
           (direction == 'above' and current_price >= target):
            alert['notified'] = True
            triggered.append(alert)
    
    # Save updated alerts
    with open(ALERTS_FILE, 'w') as f:
        json.dump(alerts, f, indent=2)
    
    # Send emails for triggered alerts
    for alert in triggered:
        user = load_user(alert['user_id'])
        if user and user.get('email'):
            send_alert_email(user['email'], alert)
```

### Email Sending

Use SendGrid (free tier: 100 emails/day) or direct SMTP:

```python
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY', '')
FROM_EMAIL = 'alerts@blueyco.in'

def send_alert_email(to_email, alert):
    """Send price alert notification via SendGrid."""
    coin = COIN_BY_ID.get(alert['coin_id'], {})
    coin_name = coin.get('name', alert['coin_id'])
    direction = alert['direction']
    target = alert['target_price']
    
    subject = f"⚡ Bluey Coin Alert: {coin_name} hit ${target}!"
    body = f"""
    Your price alert for {coin_name} has been triggered!
    
    Target: ${target} ({direction})
    
    Check current prices: https://blueyco.in
    
    Manage your alerts: https://blueyco.in (sign in required)
    """
    
    # POST to SendGrid API
    # Or use smtplib for direct SMTP
```

### Rate Limits
- Max 10 alerts per user
- Max 1 email per alert (no re-triggering)
- Future: allow re-triggering with cooldown (e.g., 7 days)

### Frontend (index.html)
- Price alert form on each coin card (visible when logged in):
  - Input: target price
  - Toggle: above / below current price
  - Button: "Set Alert"
  - Show active alert indicators on coins that have alerts set

## Email Service Decision
- **SendGrid**: Free tier 100 emails/day — generous for initial user base
- **SMTP**: Use Gmail's SMTP if available — zero cost, less reliable
- Recommendation: Start with SendGrid for deliverability
