# Feature Compatibility Matrix: Vercel Cloud Architecture

This document tracks every capability of Free Claude Code, assessing its technical compatibility with a single-project Vercel Serverless architecture.

---

## Compatibility Classification

- **SUPPORTED:** Operates natively in Vercel Serverless Functions with zero functionality loss.
- **PARTIALLY SUPPORTED:** Operates within serverless runtime constraints (e.g. execution duration limits, ephemeral `/tmp` storage).
- **NOT SUPPORTED (SERVERLESS):** Incompatible with serverless statelessness (e.g. persistent background bots, desktop tray icons). Retained in repository via the Docker alternative.

---

## Detailed Matrix

| Feature / Module | Upstream Local Behavior | Vercel Serverless Behavior | Status | Technical Details & Mitigations |
| :--- | :--- | :--- | :--- | :--- |
| **Anthropic Messages API (`/v1/messages`)** | Proxies Anthropic protocol to 61+ providers on localhost | Proxies Anthropic protocol over HTTPS on Vercel Function | **SUPPORTED** | Preserves tool calling, token estimation, and interleaved thinking blocks. |
| **OpenAI Chat Completions (`/v1/chat/completions`)** | Proxies Chat Completions to providers | Proxies Chat Completions over HTTPS | **SUPPORTED** | Native chunked streaming supported via ASGI. |
| **OpenAI Responses API (`/v1/responses`)** | Translates OpenAI Responses format | Translates OpenAI Responses format | **SUPPORTED** | 100% protocol compatibility. |
| **Google Gemini API (`/v1beta/models/...`)** | Gemini generateContent & streamGenerateContent | Gemini generateContent over HTTPS | **SUPPORTED** | Supports `alt=sse` streaming. |
| **Model Discovery (`/v1/models`)** | Returns catalog of active models | Returns catalog over HTTPS | **SUPPORTED** | Dynamic provider catalog query. |
| **SSE Streaming Response** | Local socket chunked stream | Vercel HTTP chunked transfer stream | **SUPPORTED** | Immediate flushing without serverless buffering. |
| **61 AI Providers** | HTTP clients (httpx, aiohttp, google-genai) | Async HTTP clients to external provider APIs | **SUPPORTED** | Fully outbound network enabled in Vercel Functions. |
| **Automatic Fallback & Retries** | Retries across secondary keys and providers | In-flight execution retry across configured keys | **SUPPORTED** | Governed by request timeout budget. |
| **Single-Owner Web Login (`/login`)** | None (Loopback only) | Glassmorphism login UI + HMAC session cookies | **SUPPORTED** | Enforces single-owner credentials (`OWNER_EMAIL`, `OWNER_PASSWORD`). |
| **Web Admin Dashboard (`/admin`)** | Localhost only (blocked remote IPs) | Cloud-authenticated admin panel | **SUPPORTED** | Accessible anywhere via signed session cookie or admin token. |
| **Master API Token Gateway** | Optional local proxy auth | Strict independent bearer token check | **SUPPORTED** | Enforced across all `/v1/...` routes; independent of browser session. |
| **Security Headers** | Basic headers | Defensive headers (`nosniff`, `DENY`, `strict-origin`) | **SUPPORTED** | Pure ASGI `SecurityHeadersMiddleware`. |
| **OpenClaw Client Integration** | Local port connection | Cloud HTTPS connection with Bearer token | **SUPPORTED** | OpenClaw on Windows connects to cloud proxy. |
| **Browser Code Sessions (`/admin/code`)** | Local subprocess execution via Codex app-server | Ephemeral code sessions in `/tmp/.fcc` | **PARTIALLY SUPPORTED** | Stateless sessions work; persistent workspaces across cold-starts reset unless committed to Git. |
| **Execution Duration (Timeouts)** | Unlimited local runtime | Max 60s (Hobby) / 300s (Pro) | **PARTIALLY SUPPORTED** | Model streaming starts immediately; long reasoning chains (>60s) require Pro plan or fast models. |
| **Telegram / Discord Bots** | Persistent long-polling WebSocket daemon | Long-polling daemons cannot run indefinitely on serverless | **NOT SUPPORTED (SERVERLESS)** | Retained in codebase for Model B (Docker container / VPS deployment). |
| **Desktop Tray Icon (`fcc-desktop`)** | Native Windows/macOS tray icon via Pystray | Headless cloud environment | **NOT SUPPORTED (SERVERLESS)** | Excluded from serverless `requirements.txt`. |
