# Vercel 2026 Production Architecture: Free Claude Code Cloud

## 1. Executive Summary
Free Claude Code Cloud is deployed as **ONE unified Vercel Project** running on the Vercel Serverless platform (Python 3.12 runtime). It delivers high-concurrency request routing, streaming Server-Sent Events (SSE), and a private administrative dashboard while incurring **zero baseline hosting costs**.

---

## 2. Platform Specification & Limits (Hobby / Serverless)

| Dimension | Specification | Implementation in FCC Cloud |
| :--- | :--- | :--- |
| **Hosting Platform** | Vercel (Hobby Free Tier) | Single Project deployment |
| **Runtime** | Python 3.12 (AWS Lambda arm64/x86_64) | Managed via `runtime.txt` & `vercel.json` |
| **Max Execution Duration** | Up to 60 seconds (Hobby limit) | Configured `maxDuration: 60` in `vercel.json` |
| **Memory Allocation** | 1024 MB | Configured `memory: 1024` for low latency |
| **Filesystem Storage** | Ephemeral `/tmp` (512 MB - 10 GB) | Dynamic redirect via `FCC_CONFIG_DIR=/tmp/.fcc` |
| **Cold Start Mitigation** | ASGI App Pre-warming & Lazy Imports | `api/index.py` caches initialized FastAPI instance |
| **Streaming Support** | Server-Sent Events (SSE) | HTTP streaming supported natively via Transfer-Encoding: chunked |

---

## 3. Directory & Routing Architecture

```
free-claude-code-cloud/
├── api/
│   └── index.py            <-- Vercel entrypoint (exports ASGI `app`)
├── vercel.json             <-- Function definitions, memory, timeouts, rewrites
├── runtime.txt             <-- Defines python-3.12
├── requirements.txt        <-- Production cloud dependencies
├── src/free_claude_code/
│   ├── api/                <-- FastAPI routers, auth, middlewares, handlers
│   ├── application/        <-- Model routing, token estimation, rate tracking
│   ├── config/             <-- Ephemeral paths, provider catalog, settings
│   └── core/               <-- Wire protocol translation (Anthropic/OpenAI/Gemini)
└── ...
```

### `vercel.json` Configuration:
```json
{
  "version": 2,
  "functions": {
    "api/index.py": {
      "runtime": "python@3.12",
      "maxDuration": 60,
      "memory": 1024
    }
  },
  "routes": [
    {
      "src": "/(.*)",
      "dest": "api/index.py"
    }
  ]
}
```

---

## 4. Cold Start & Concurrency Optimization
1. **Singleton Application Instance:** `api/index.py` builds the FastAPI application once during Lambda container initialization. Subsequent requests hitting warm instances execute with sub-5ms overhead.
2. **Lean Dependency Surface:** Desktop GUI modules (`tkinter`, `webview`, `pyqt`) and build harnesses are strictly excluded from `requirements.txt`.
3. **Stateless Scalability:** Since sessions are cryptographically signed and verify without state lookups, requests can be served by any Vercel region or worker instance instantly.
