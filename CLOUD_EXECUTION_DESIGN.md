# Cloud Execution Design: Serverless Request Lifecycle

## 1. Request Lifecycle Overview
In Free Claude Code Cloud, every incoming request follows a deterministic pipeline through ASGI middlewares, security gates, protocol translation, and streaming delivery:

```
[ INGRESS ]
    │
    ▼
1. Vercel Edge / TLS Termination (HTTPS)
    │
    ▼
2. RequestCorrelationMiddleware (Generates unique req_xxx ID)
    │
    ▼
3. SecurityHeadersMiddleware (Attaches nosniff, DENY, etc.)
    │
    ▼
4. AdminNoStoreMiddleware (Adds no-store headers to admin routes)
    │
    ▼
5. Routing & Authentication Dispatch:
    ├── HTML Browser Request -> Owner Session Check -> /admin or /login
    ├── Admin API Request -> require_loopback_admin -> Cookie/Bearer Token Check
    └── Gateway API (/v1/*) -> require_proxy_auth -> MASTER_API_TOKEN Check
    │
    ▼
6. Wire Protocol Parser & Model Router:
    ├── Anthropic Messages API -> Maps to configured upstream (Gemini/OpenAI/etc.)
    ├── Streaming SSE Generator -> Emits incremental chunk stream
    └── Tool Call Interceptor -> Handles client function calling schemas
    │
    ▼
[ EGRESS: Streaming Response via Chunked Transfer-Encoding ]
```

---

## 2. Streaming Protocol Preservation
One of the most critical aspects of Free Claude Code is streaming responses for developer tools like Claude Code CLI and OpenClaw.
- **Protocol:** Server-Sent Events (`text/event-stream; charset=utf-8`).
- **Buffering Control:** Vercel functions support streaming chunked transfer encoding out of the box when the `maxDuration` allows sufficient execution time.
- **Keep-Alives:** Periodic ping comments (`: ping\n\n`) are dispatched during prolonged generation pauses to ensure intermediate cloud proxies and client read timeouts remain active.

---

## 3. Ephemeral Filesystem Management
- **Issue:** Serverless containers feature read-only root filesystems, with only `/tmp` writable.
- **Solution:** `paths.py` checks `FCC_CONFIG_DIR` or defaults to `/tmp/.fcc` when running inside Vercel (`os.getenv("VERCEL")`) or AWS Lambda (`os.getenv("AWS_LAMBDA_FUNCTION_NAME")`).
- **Storage Profile:**
  - `/tmp/.fcc/fcc.db`: Ephemeral SQLite database used for active session tracking.
  - `/tmp/.fcc/logs/`: Ephemeral diagnostics log files.
- **Lifecycle:** Files in `/tmp` persist across warm invocations of the same container instance, but are purged when the instance scales to zero. All proxy configurations are sourced from encrypted environment variables, ensuring zero data loss upon container teardown.
