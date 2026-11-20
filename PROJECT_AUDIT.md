# Project Audit: Free Claude Code Cloud

**Date:** November 2026  
**Auditor:** Principal Software Architect & Application Security Lead  
**Target Repository:** `free-claude-code-cloud` (Private)  
**Upstream Repository:** `https://github.com/Alishahryar1/free-claude-code`  
**Execution Target:** Single-Project Vercel Cloud Architecture  

---

## 1. Current Repository State

The repository is an autonomous AI Gateway and Coding Workspace built on Python 3.12/3.14 with FastAPI. It translates requests from standard AI tool protocols (Anthropic Messages, OpenAI Chat Completions, OpenAI Responses, Google Gemini) to 61+ upstream AI model providers.

### Key Metrics
- **Source Modules:** `src/free_claude_code/` (api, application, config, core, harnesses, messaging, providers, runtime)
- **Frontend Assets:** `src/free_claude_code/api/admin_static/` (Vanilla ES6 JavaScript, modular CSS, HTML5 SPA)
- **Automated Tests:** 263 unit, contract, API, authentication, and cloud deployment tests passing with 0 failures.
- **Entry Points:**
  - `api/index.py`: Serverless ASGI entry point for Vercel Functions.
  - `free_claude_code.cli.entrypoints:serve`: Local CLI daemon entrypoint (`fcc-server`).
  - `free_claude_code.runtime.bootstrap:build_asgi_app`: ASGI application composition root.

---

## 2. In-Depth Component Analysis

### 2.1 Routing & Protocols
The application exposes four distinct AI generation protocols:
1. **Anthropic Messages Protocol:** `POST /v1/messages`, `POST /v1/messages/count_tokens`
   - Wire format: Anthropic JSON with SSE streaming (`event: message_start`, `content_block_delta`, `message_delta`, etc.).
   - Interleaved thinking blocks (`<thought>...</thought>`) parsed and preserved.
2. **OpenAI Chat Completions Protocol:** `POST /v1/chat/completions`
   - Wire format: OpenAI Chat JSON with chunked SSE streaming (`choices[0].delta.content`).
3. **OpenAI Responses Protocol:** `POST /v1/responses`
   - Wire format: OpenAI Responses API specification.
4. **Google Gemini Protocol:** `POST /v1beta/models/{resource:path}`, `POST /v1/models/{resource:path}`
   - Action routing: `:generateContent` and `:streamGenerateContent?alt=sse`.
5. **Model Catalog Discovery:** `GET /v1/models`
   - Lists active provider models and capabilities formatted for OpenAI/OpenClaw clients.

### 2.2 Security Architecture (Pre-Transformation vs Target)
- **Upstream Flaw:** Local-only loopback check in `admin_security.py` rejected all non-127.0.0.1 requests with 403 Forbidden.
- **Upstream Flaw:** `PROXY_AUTH_ENABLED` defaulted to `False`, exposing `/v1/...` publicly if deployed without explicit config.
- **Target Single-Owner Security Model:**
  - `OWNER_EMAIL` + `OWNER_PASSWORD`: Strictly required for web dashboard access (`/login`, `/admin`).
  - `MASTER_API_TOKEN`: Completely independent bearer token strictly required for external API gateway clients (`/v1/...`).
  - No public registration, signup, or password reset. Fail closed if credentials are unset.

### 2.3 Provider Ecosystem
Supports 61 AI providers with dynamic fallback and key rotation:
- NVIDIA NIM (Nemotron, Llama 3.3, Mistral Large)
- OpenRouter (unified multi-model router)
- Groq (ultra-low-latency Llama and Mixtral inference)
- Google Gemini (Gemini 2.0 Flash, Flash Thinking)
- OpenAI (GPT-4o, o1, o3-mini)
- DeepSeek (DeepSeek V3, DeepSeek R1)
- Cerebras, Together AI, Mistral, SambaNova, Fireworks, GitHub Copilot

### 2.4 State & Persistence Audit
- **Core LLM Proxying:** 100% stateless. Requires zero database queries.
- **Code Sessions & Prompts:** Uses embedded SQLite (`fcc.db`).
- **Filesystem Assumptions:** Upstream assumed writable `~/.fcc`. Remediated to check `FCC_CONFIG_DIR` and default to `/tmp/.fcc` in serverless environments.

---

## 3. Route Inventory & Classification

| Route | Method | Access Level | Description | Security Requirements |
| :--- | :--- | :--- | :--- | :--- |
| `/login` | GET | `PUBLIC` | Owner login interface | Modern glassmorphism UI, rate-limited |
| `/api/auth/login` | POST | `PUBLIC` | Authenticate owner credentials | Constant-time password check, issues signed cookie |
| `/api/auth/logout` | POST | `OWNER_SESSION` | Invalidate session | Clears session cookie, CSRF protected |
| `/api/auth/session` | GET | `PUBLIC` | Session status check | Returns `{authenticated: bool}` |
| `/` | GET | `HYBRID` | Root endpoint | If authenticated, renders dashboard; else login |
| `/health` | GET | `PUBLIC` | Healthcheck probe | Returns `{"status": "healthy"}` |
| `/admin` | GET | `OWNER_SESSION` | Admin UI SPA | Requires valid owner cookie / Bearer token |
| `/admin/assets/{v}/{f}`| GET | `PUBLIC` | Static CSS/JS/SVG assets | Cacheable static delivery |
| `/admin/api/config` | GET/POST | `OWNER_SESSION` | Admin configuration API | Masked keys, owner session only |
| `/admin/code` | GET | `OWNER_SESSION` | Browser coding workspace | Owner session only |
| `/admin/api/code/...` | ANY | `OWNER_SESSION` | Code sessions API & SSE | Owner session only |
| `/v1/messages` | POST | `MASTER_API_TOKEN` | Anthropic Messages Gateway | Master API Token required (Bearer/x-api-key) |
| `/v1/chat/completions`| POST | `MASTER_API_TOKEN` | OpenAI Chat Gateway | Master API Token required |
| `/v1/responses` | POST | `MASTER_API_TOKEN` | OpenAI Responses Gateway | Master API Token required |
| `/v1/models` | GET | `MASTER_API_TOKEN` | OpenAI Models Discovery | Master API Token required |
| `/v1beta/models/...` | POST | `MASTER_API_TOKEN` | Gemini Generation Gateway | Master API Token required |
