# Remote Desktop Security — OttomanDevice v0.2.0

**Status:** Implemented (Sprint 23)  
**Scope:** Server-issued JWT session tokens for WebSocket authentication

---

## 1. Authentication flow

```
┌─────────────┐     POST /remote-desktop-session      ┌─────────────────────┐
│  Dashboard  │ ────────────────────────────────────► │ Supabase Edge Func  │
│  (browser)  │     Authorization: Bearer <user>      │ remote-desktop-session│
│             │     { device_id }                     │                     │
│             │ ◄──────────────────────────────────── │  ✓ verify user      │
│             │     { token, session_id, expires }    │  ✓ verify device    │
└──────┬──────┘                                       │  ✓ sign JWT (60s)   │
       │                                                └─────────────────────┘
       │  ws://127.0.0.1:9842/remote-desktop/v1
       │  HELLO → AUTH { token } → START_STREAM
       ▼
┌─────────────┐
│ Device Agent│  Validates JWT signature, expiry, device_id, session_id
│ WebSocket   │  Enforces single-use (jti replay guard)
└─────────────┘
```

### Steps

1. **Dashboard** obtains a Supabase user session (anonymous or authenticated).
2. **Dashboard** calls the `remote-desktop-session` Edge Function with `device_id`.
3. **Edge Function** verifies the user, confirms the device exists in `devices_enhanced`, and issues a signed JWT (60-second lifetime).
4. **Dashboard** opens a WebSocket to the device agent and sends `HELLO`, then `AUTH` with the JWT.
5. **Agent** validates the token and transitions the session to `ACTIVE`.

The dashboard **never** holds a signing secret. JWT signing keys exist only on the Edge Function and device agent.

---

## 2. Token lifecycle

| Phase | Actor | Action |
|-------|-------|--------|
| Issue | Edge Function | Creates JWT with `device_id`, `session_id`, `iat`, `exp`, `jti` |
| Transport | Dashboard | Sends token once in `AUTH` payload over WebSocket |
| Validate | Agent | Verifies HS256 signature, expiry, claim match |
| Consume | Agent | Records `jti` in replay guard (single-use) |
| Expire | Clock | Token invalid after 60 seconds (`exp`) |
| Renew | Dashboard | Requests new token before connect or on `TOKEN_EXPIRED` |

### JWT claims

| Claim | Purpose |
|-------|---------|
| `device_id` | Must match the agent's registered device |
| `session_id` | Unique session identifier for this auth attempt |
| `iat` | Issued-at timestamp (Unix seconds) |
| `exp` | Expiration timestamp (Unix seconds, `iat + 60`) |
| `jti` | Unique token ID for replay protection |

---

## 3. Threat model

| Threat | Mitigation |
|--------|------------|
| Stolen signing secret in browser | **Removed.** Dashboard has no secret; tokens are server-issued. |
| Token interception (MITM) | Use TLS/WSS in production; localhost-only binding in v0.2.0 dev. |
| Replay of captured AUTH token | **Single-use `jti` guard** on agent; reused tokens rejected. |
| Token reuse across devices | `device_id` claim validated against agent identity. |
| Expired token use | `exp` validated; agent returns `TOKEN_EXPIRED`. |
| Unauthorized session request | Edge Function requires valid Supabase user JWT. |
| Session hijacking (second viewer) | One active WebSocket session per device (`SESSION_BUSY`). |
| Brute-force token guessing | 60-second TTL + UUID `jti`/`session_id`; HS256 with strong secret. |

### Out of scope (v0.2.0)

- Role-based access control (RBAC) per device
- Audit log persistence for auth events
- Hardware-bound device attestation
- mTLS between dashboard and agent

---

## 4. Replay protection

Each issued JWT contains a unique `jti` (JWT ID). When the agent accepts a token:

1. `jti` is checked against an in-memory **replay guard**.
2. If `jti` was previously consumed → reject with `TOKEN_REUSED`.
3. On success, `jti` is stored until `exp` passes, then purged.

This ensures each token authenticates **at most one** WebSocket session, even if an attacker replays the `AUTH` message.

---

## 5. Environment configuration

| Variable | Location | Purpose |
|----------|----------|---------|
| `REMOTE_DESKTOP_JWT_SECRET` | Agent `.env`, Edge Function secrets | HS256 signing key |
| `SUPABASE_SERVICE_ROLE_KEY` | Edge Function (auto-injected) | Device existence check |
| `VITE_SUPABASE_URL` | Dashboard `.env` | Supabase client |
| `VITE_SUPABASE_ANON_KEY` | Dashboard `.env` | Supabase client |

**Never** set `VITE_REMOTE_DESKTOP_TOKEN_SECRET` or any signing secret in the dashboard.

Agent settings (`config/default.yaml` → `remote_desktop`):

- `jwt_secret_env`: `REMOTE_DESKTOP_JWT_SECRET`
- `jwt_algorithm`: `HS256`
- `token_ttl_seconds`: `60` (must match Edge Function issuance TTL)

---

## 6. Logging policy

The agent logs only these auth events (no tokens, secrets, or claim values):

- `Session authenticated`
- `Session rejected`
- `Token expired`
- `Token reused`

---

## 7. Future RBAC integration

The Edge Function already verifies an authenticated Supabase user before issuing tokens. Future RBAC can extend this checkpoint:

1. **Device ownership table** — map `user_id` → allowed `device_id` values.
2. **Edge Function gate** — reject token requests for devices the user does not own.
3. **JWT claims** — add `sub` (user ID) and `scopes` for agent-side audit.
4. **RLS policies** — restrict `devices_enhanced` SELECT to authorized operators.
5. **Session audit table** — persist `session_id`, `user_id`, `device_id`, `issued_at` for compliance.

The agent validation path remains unchanged; only the Edge Function issuance policy becomes more restrictive.

---

## 8. Error codes

| Code | Meaning | Dashboard action |
|------|---------|------------------|
| `AUTH_FAILED` | Invalid signature, malformed token, or wrong `device_id` | Reconnect with new token |
| `TOKEN_EXPIRED` | `exp` passed | Request new token, reconnect |
| `TOKEN_REUSED` | `jti` already consumed | Request new token, reconnect |
| `SESSION_BUSY` | Another viewer connected | Fall back to storage preview |
| `TIMEOUT` | Keepalive missed | Reconnect with new token |

---

## 9. Backward compatibility

- v0.1.0 storage preview fallback unchanged when WebSocket auth fails.
- HMAC client-side tokens (`REMOTE_DESKTOP_TOKEN_SECRET`) are **removed**; agents accept JWT only.
- Streaming protocol (`START_STREAM`, `FRAME`, `STOP_STREAM`) is unchanged.