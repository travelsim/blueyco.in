#!/usr/bin/env python3
import urllib.request
import json

with open("/Users/jameslove/.render_token") as f:
    token = f.read().strip()

# Set EPN_CAMPAIGN_ID as an env var on the blueycoin service
# This is ready to run once James provides the Campaign ID
# Replace YOUR_EPN_CAMPAIGN_ID with the actual value

CAMPAIGN_ID = "YOUR_EPN_CAMPAIGN_ID"  # <-- REPLACE THIS

if CAMPAIGN_ID == "YOUR_EPN_CAMPAIGN_ID":
    print("Campaign ID not provided yet. Run this script with the actual Campaign ID.")
    print("e.g.: EPN_CAMPAIGN_ID=1234567 python3 set_epn_env.py")
    import sys
    sys.exit(1)

req = urllib.request.Request(
    f"https://api.render.com/v1/services/srv-d8ah7rmgvqtc73csctng/env-vars",
    method="PUT",
    data=json.dumps({
        "EPN_CAMPAIGN_ID": {
            "value": CAMPAIGN_ID
        }
    }).encode()
)
req.add_header("Authorization", f"Bearer {token}")
req.add_header("Content-Type", "application/json")

try:
    resp = urllib.request.urlopen(req, timeout=15)
    print(f"Status: {resp.status}")
    print("EPN_CAMPAIGN_ID set successfully!")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"HTTP {e.code}: {body}")
except Exception as e:
    print(f"Error: {e}")

# Now trigger a new deploy so the env var takes effect
print("Now triggering redeploy to pick up the new env var...")
req2 = urllib.request.Request(
    "https://api.render.com/v1/services/srv-d8ah7rmgvqtc73csctng/deploys",
    method="POST",
    data=json.dumps({"clearCache": "do_not_clear"}).encode()
)
req2.add_header("Authorization", f"Bearer {token}")
req2.add_header("Content-Type", "application/json")

try:
    resp2 = urllib.request.urlopen(req2, timeout=30)
    data = json.loads(resp2.read().decode())
    print(f"Deploy triggered: {data.get('id')} - status: {data.get('status')}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"Deploy HTTP {e.code}: {body}")
except Exception as e:
    print(f"Deploy error: {e}")
