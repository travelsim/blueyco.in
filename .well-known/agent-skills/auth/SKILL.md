# auth.md

## Bluey Coin Tracker Agent Authentication

Autonomous AI agents can interact with the Bluey Coin Tracker (`blueyco.in`) platform using standard protocol discovery.

### Metadata Endpoints
- **OAuth Authorization Server**: `https://blueyco.in/.well-known/oauth-authorization-server`
- **OpenID Connect Discovery**: `https://blueyco.in/.well-known/openid-configuration`
- **Protected Resource Metadata**: `https://blueyco.in/.well-known/oauth-protected-resource`
- **JWKS Endpoint**: `https://blueyco.in/.well-known/jwks.json`

### Supported Registration & Access Methods
1. **Public Read-Only API**:
   - `GET /api/prices`: Public pricing snapshot (no token required).
   - `GET /api/price-history`: Historical pricing trends (no token required).
2. **Identity Assertion**:
   - Supported assertions: `verified_email`, `urn:ietf:params:oauth:token-type:id-jag`.
   - Registration & token exchange URI: `https://blueyco.in/api/auth`.
3. **Session Verification**:
   - `GET /api/auth`: Verifies current session or token status.
