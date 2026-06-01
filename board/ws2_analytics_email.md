# WS-2: Analytics + Email Capture — cod3r spec

## Goal
Add privacy-focused analytics and email newsletter signup to Blueycoin. Build audience for future monetisation.

## 1. Analytics

### Option A: Plausible (Recommended)
- Self-hosted or plausible.io SaaS ($9/mo for 10k pageviews)
- Single script tag: `<script defer data-domain="blueyco.in" src="https://plausible.io/js/script.js"></script>`
- Zero impact on page performance, GDPR-compliant, no cookie banner needed
- Config: add to `index.html` `<head>`, before the CSP or update CSP to allow `https://plausible.io`

### Option B: Umami
- Self-hosted on Render or Railway (free tier)
- Open-source, self-contained
- Similar single-script approach

### Recommendation
Start with Plausible Cloud ($9/mo) — no maintenance, just one line of code.
If budget-conscious, self-host Umami on the same server.

### CSP Update
Current CSP: `default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com;`
Add: `https://plausible.io` to `script-src` and `connect-src`

## 2. Email Capture

### Mailchimp Setup
- James creates free Mailchimp account (up to 500 contacts free)
- Create an audience "Bluey Coin Tracker"
- Create signup form with fields: Email, Series Interest (checkboxes: 2024 Dollarbucks, 2025 Christmas, 2026 Bluey 2)

### Server-side (server.py)
Add endpoint `POST /api/subscribe`:

```python
MAILCHIMP_API_KEY = os.environ.get('MAILCHIMP_API_KEY', '')
MAILCHIMP_LIST_ID = os.environ.get('MAILCHIMP_LIST_ID', '')
MAILCHIMP_SERVER  = os.environ.get('MAILCHIMP_SERVER', 'us1')  # datacenter prefix

def do_POST(self):
    if self.path == '/api/subscribe':
        # Parse body: { email, interests: [...] }
        # Validate email format
        # POST to https://{server}.api.mailchimp.com/3.0/lists/{list_id}/members
        # Return 200 on success, 400 on validation error
```

### Frontend (index.html)
Add a signup section in the footer or as a collapsible panel:

```
┌─────────────────────────────────┐
│  📬 Bluey Coin Alerts           │
│                                 │
│  Get notified when new Bluey    │
│  coins drop + weekly price      │
│  digest to your inbox.          │
│                                 │
│  [email@example.com            ]│
│  ☐ 2024 Dollarbucks             │
│  ☐ 2025 Christmas               │
│  ☐ 2026 Bluey 2                 │
│                                 │
│  [Subscribe →]                  │
│                                 │
│  No spam, unsubscribe anytime.  │
└─────────────────────────────────┘
```

### Email Content Ideas
- New coin series launch alert (highest value — collectors want to know ASAP)
- Weekly price digest: top 3 movers (up/down) in the last 7 days
- Monthly market report: best performing coins, new listings

### Privacy
- Add privacy notice next to subscribe button
- CSP must allow POST to Mailchimp API (or proxy through server)
- Recommendation: proxy through server.py to keep Mailchimp API key server-side
