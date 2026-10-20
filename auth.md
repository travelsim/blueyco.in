# auth.md

## Bluey Coin Tracker Agent Registration & Authentication

Autonomous AI agents can discover, register, and authenticate with Bluey Coin Tracker (`blueyco.in`).

### Discovery Endpoints
- **OAuth Authorization Server**: `https://blueyco.in/.well-known/oauth-authorization-server`
- **OpenID Connect Discovery**: `https://blueyco.in/.well-known/openid-configuration`
- **Protected Resource Metadata**: `https://blueyco.in/.well-known/oauth-protected-resource`
- **JWKS Endpoint**: `https://blueyco.in/.well-known/jwks.json`

### Agent Registration & Access Flow
Autonomous agents can obtain API credentials via token exchange:
1. Issue a POST request to `https://blueyco.in/api/auth` with:
   - `grant_type`: `urn:ietf:params:oauth:grant-type:token-exchange`
   - `subject_token`: Agent identity assertion (e.g. verified email or ID-JAG token)
   - `subject_token_type`: `urn:ietf:params:oauth:token-type:id-jag`
2. Receive JSON response containing Bearer access token:
   ```json
   {
     "access_token": "token",
     "token_type": "Bearer",
     "expires_in": 3600
   }
   ```
3. Include the token in subsequent API requests via the `Authorization: Bearer <access_token>` header.
