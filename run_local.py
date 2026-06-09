#!/usr/bin/env python
"""Launch script for blueyco.in dynamic site on port 8780.

Loads .env from the project root so EPN_CAMPAIGN_ID and friends are set
before server.py is imported (server.py reads env vars at module import
time, not lazily).
"""
import os
import sys

# Try to load .env via python-dotenv if available, else fall back to a
# minimal hand-rolled parser (the file is simple KEY=VALUE lines).
LOG = r"C:\Users\James Love\.hermes\work\blueyco-in-dynamic\run_local.log"
def _log(msg):
    with open(LOG, "a") as f:
        f.write(msg + "\n")

PROJECT = r"C:\Users\James Love\.hermes\work\blueyco-in-dynamic"
ENV_FILE = os.path.join(PROJECT, ".env")

os.chdir(PROJECT)
sys.path.insert(0, PROJECT)

# 1. Hand-rolled .env loader (don't require python-dotenv)
if os.path.exists(ENV_FILE):
    _log(f"[run_local] Loading .env from {ENV_FILE}")
    with open(ENV_FILE) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # Don't clobber pre-existing real env vars
            os.environ.setdefault(key, val)
    _log(f"[run_local]   EPN_CAMPAIGN_ID in env: {'EPN_CAMPAIGN_ID' in os.environ}")
    if "EPN_CAMPAIGN_ID" in os.environ:
        _log(f"[run_local]     value: {os.environ['EPN_CAMPAIGN_ID']}")

os.environ.setdefault("PORT", "8780")

_log(f"[run_local] cwd={os.getcwd()}")
_log(f"[run_local] PORT={os.environ.get('PORT')}")
_log(f"[run_local] EPN_CAMPAIGN_ID={os.environ.get('EPN_CAMPAIGN_ID', '(not set)')}")

_log("Loading server module...")
import server  # noqa: E402
_log(f"Module loaded. COINS={len(server.COINS)}")
_log(f"  server.EPN_CAMPAIGN_ID={server.EPN_CAMPAIGN_ID!r}")
_log(f"  server._price_history list length: {len(server._price_history)}")

port = int(os.environ["PORT"])
_log(f"Starting ThreadingHTTPServer on 0.0.0.0:{port}...")
server.ThreadingHTTPServer(("0.0.0.0", port), server.Handler).serve_forever()

