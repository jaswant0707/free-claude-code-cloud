# Architecture Decision Records (ADRs)

---

## ADR-001: Unified Single-Project Vercel Serverless Architecture

- **Status:** ACCEPTED
- **Context:** The application needs 24/7 cloud availability without requiring the user's laptop to stay online. Multi-host architectures (Render, Railway, Fly.io, Cloudflare Workers) introduce architectural fragmentation, additional cost, and complex secrets management.
- **Decision:** Consolidate the entire production application (Frontend, Login, Admin UI, API Gateway, Streaming, and Provider orchestration) into **one Vercel project** using `@vercel/python` and FastAPI.
- **Consequences:** Zero fixed infrastructure costs on Vercel Hobby. Scale-to-zero efficiency. Simplifies deployment to a single git repository push.

---

## ADR-002: Zero External Database (Omission of Supabase)

- **Status:** ACCEPTED
- **Context:** The prompt instructs: *"Database preference: No database unless required. Consider Supabase only when the existing application's architecture requires persistent database functionality."*
- **Decision:** Omit Supabase and all external hosted databases.
- **Rationale:**
  1. The core LLM proxying engine (`/v1/messages`, `/v1/chat/completions`, etc.) is completely stateless. It routes requests directly to upstream AI providers and streams tokens back without database I/O.
  2. Single-owner credentials (`OWNER_EMAIL`, `OWNER_PASSWORD`) and `MASTER_API_TOKEN` are read securely from server-side environment variables.
  3. Where database tables exist in the original codebase (Code sessions, prompt history), Python's built-in `sqlite3` in `/tmp/fcc.db` satisfies all local execution requirements.
  4. Introducing an external database like Supabase would add network round-trip latency to every request, introduce connection pool exhaustion risks in serverless, and incur external management overhead with zero functional benefit.

---

## ADR-003: Dual-Boundary Independent Authentication Architecture

- **Status:** ACCEPTED
- **Context:** The application serves two completely distinct consumer types:
  1. The human owner using web browsers (desktop/mobile) for configuration and administration.
  2. Automated external coding agents (OpenClaw, Claude Code CLI, Cursor, Cline) invoking the API gateway.
- **Decision:** Implement two completely decoupled authentication boundaries:
  - **Boundary 1 (Human Owner):** `OWNER_EMAIL` + `OWNER_PASSWORD` validated at `/api/auth/login`, issuing a signed `HttpOnly`, `SameSite=Lax`, `Secure` session cookie. Protects `/admin`, `/admin/api/...`, and `/admin/code`.
  - **Boundary 2 (External API Gateway):** Independent `MASTER_API_TOKEN` validated via `Authorization: Bearer <MASTER_API_TOKEN>` or `x-api-key`. Protects `/v1/messages`, `/v1/chat/completions`, `/v1/responses`, `/v1/models`, and Gemini endpoints.
- **Rules of Separation:**
  - Browser sessions CANNOT authenticate external API gateway endpoints.
  - Master API Tokens CANNOT authenticate browser admin sessions.
  - Browser logout does NOT invalidate the Master API Token.
  - Expired browser sessions do NOT affect external API clients.

---

## ADR-004: Stateless Cryptographic Session Tokens for Serverless

- **Status:** ACCEPTED
- **Context:** In Vercel Serverless, function instances spin up and terminate independently across global edge locations. In-memory session registries do not synchronize across separate lambda containers.
- **Decision:** Implement HMAC-SHA256 signed session tokens stored in `HttpOnly` cookies.
- **Structure:** `base64(payload).signature`, where payload contains `{email, issued_at, expires_at, nonce}`.
- **Verification:** Any warm or cold serverless function can verify the signature and expiration timestamp in constant time using a server-side secret derived from `OWNER_PASSWORD` and an internal salt.
- **Logout:** The logout endpoint overwrites the cookie with `Max-Age=0` and invalidates the client session.

---

## ADR-005: Python 3.12 Universal Syntax Modernization

- **Status:** ACCEPTED
- **Context:** Upstream code utilized Python 3.14-only unparenthesized `except E1, E2:` grammar in 54 locations, causing immediate `SyntaxError` on Python 3.12 (Vercel standard runtime).
- **Decision:** Surgically update all 54 multi-exception clauses to standard parenthesized syntax `except (E1, E2):` and set `pyproject.toml` to `requires-python = ">=3.12"`.
- **Consequences:** 100% backward and forward compatibility across Python 3.12, 3.13, and 3.14.

---

## ADR-006: Pure ASGI Security Middleware for Streaming Integrity

- **Status:** ACCEPTED
- **Context:** Starlette's `BaseHTTPMiddleware` buffers response streams into memory to process headers, which can break or delay Server-Sent Events (SSE) streaming tokens.
- **Decision:** Implement `SecurityHeadersMiddleware` and `AdminNoStoreMiddleware` as pure ASGI callable interceptors operating directly on `http.response.start`.
- **Consequences:** Zero latency overhead, zero streaming buffering, and guaranteed security headers on all responses.
