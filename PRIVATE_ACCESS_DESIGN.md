# Private Access Design Document: Free Claude Code Cloud

## 1. Executive Summary

Free Claude Code Cloud is engineered strictly as a **Single-Owner Private AI Workspace and Master API Gateway**. It is not a multi-tenant public SaaS application. The access model is built upon zero-trust boundaries, fail-closed access control, and complete separation between browser workspace interaction and programmatic machine-to-machine API consumption.

---

## 2. Access Boundary Architecture

The platform enforces two completely non-intersecting authentication boundaries:

```
+-----------------------------------------------------------------------------------+
|                           FREE CLAUDE CODE CLOUD                                  |
|                                                                                   |
|  [ BOUNDARY 1: SINGLE-OWNER WEB BROWSER WORKSPACE ]                              |
|                                                                                   |
|  Owner Browser ---> GET / ---> 303 Redirect ---> /login                          |
|                     |                                                             |
|                     +---> POST /api/auth/login ---> Validates OWNER_EMAIL/PASSWORD |
|                     |                               Sets fcc_session cookie       |
|                     v                                                             |
|              /admin, /admin/code, /admin/api/* (Protected by fcc_session)         |
|                                                                                   |
|  -------------------------------------------------------------------------------  |
|                                                                                   |
|  [ BOUNDARY 2: UNIVERSAL MACHINE-TO-MACHINE API GATEWAY ]                         |
|                                                                                   |
|  External Client ---> POST /v1/messages, /v1/chat/completions, /v1beta/models     |
|  (OpenClaw, Claude    |                                                           |
|   Code CLI, Cursor)   +---> Requires Authorization: Bearer <MASTER_API_TOKEN>     |
|                       |     or x-api-key: <MASTER_API_TOKEN>                      |
|                       v                                                           |
|               Streaming SSE responses, Tool Calls, Model Routing                  |
+-----------------------------------------------------------------------------------+
```

### Boundary 1: Single-Owner Web UI Session
- **Target Surfaces:** `/`, `/admin`, `/admin/code`, `/admin/model_config`, `/admin/integrations`, and `/admin/api/*`.
- **Identity Mechanism:** Single configured email (`OWNER_EMAIL`) and cryptographic password (`OWNER_PASSWORD`).
- **Session Token:** Stateless HMAC-SHA256 token delivered via an `HttpOnly`, `SameSite=Lax`, `Secure` cookie named `fcc_session`.
- **Strict Isolation:** A valid `fcc_session` cookie **CANNOT** authenticate requests against Boundary 2 external API endpoints (`/v1/messages`, `/v1/chat/completions`, etc.).

### Boundary 2: Machine-to-Machine Master API Gateway
- **Target Surfaces:** `/v1/messages`, `/v1/messages/count_tokens`, `/v1/chat/completions`, `/v1/responses`, `/v1/models`, `/v1beta/models/*`, `/stop`.
- **Identity Mechanism:** Independent `MASTER_API_TOKEN` (or fallback `PROXY_AUTH_TOKEN`).
- **Transport Mechanism:** `Authorization: Bearer <MASTER_API_TOKEN>`, `x-api-key: <MASTER_API_TOKEN>`, or `x-goog-api-key: <MASTER_API_TOKEN>`.
- **Strict Isolation:** Browser sessions cannot bypass the token requirement. Logging out of the web UI does not invalidate external API access, preserving unattended tool workflows.

---

## 3. Threat Modeling & Defense Strategies

| Threat Scenario | Vector | Mitigation Mechanism |
| :--- | :--- | :--- |
| **Public Probe / Port Scan** | Automated scanner hits `/` or `/v1/messages` | Fail-closed: `/` redirects browsers to `/login`; API clients receive 401 Unauthorized without leaking provider configs or backend traces. |
| **Credential Brute Force** | Dictionary attack against `/api/auth/login` | IP-based sliding-window rate limiter caps attempts at 5 requests per 60 seconds (HTTP 429). |
| **Timing Side-Channel** | Measuring byte comparison timing on secrets | All string comparisons utilize `secrets.compare_digest` for constant-time evaluation. |
| **Cookie Hijacking / XSS** | Client script accessing session | Cookies flagged `HttpOnly` and `SameSite=Lax`. `Content-Security-Policy` and `X-Content-Type-Options: nosniff` prevent script injection. |
| **Clickjacking** | Embedding workspace in malicious iframe | `X-Frame-Options: DENY` sent on 100% of responses via `SecurityHeadersMiddleware`. |
| **Credential Compromise** | Exposure of old test password | Password in production must be injected via Vercel Encrypted Environment Variables. Local git repository has zero credentials. |

---

## 4. Verification Evidence

The private access design is fully covered by automated regression tests in `tests/api/test_owner_auth.py`:
- `test_browser_root_redirects_unauthenticated` -> Verified 303 Redirect to `/login`.
- `test_admin_redirects_unauthenticated_browser` -> Verified 307 Redirect to `/login?next=/admin`.
- `test_dual_boundary_separation` -> Confirmed `/v1/models` rejects browser cookie with 401 and strictly requires `MASTER_API_TOKEN`.
- `test_login_rate_limiting` -> Verified 6th brute-force attempt receives HTTP 429.
