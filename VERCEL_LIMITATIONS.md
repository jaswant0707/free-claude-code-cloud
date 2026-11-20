# Vercel Serverless Limitations & Engineering Adaptations

## 1. Overview
Deploying a complex Python application to Vercel requires understanding and engineering around serverless constraints.

---

## 2. Platform Constraints & Solutions Matrix

| Vercel Limitation | Impact on FCC | Engineering Adaptation |
| :--- | :--- | :--- |
| **Execution Duration Cap** (Hobby: 60s max) | Long LLM generations could time out if exceeding 60 seconds. | 1. Configured `maxDuration: 60` in `vercel.json`.<br>2. Streaming SSE transmits tokens immediately as they arrive, maintaining active connection.<br>3. For massive batches, clients should chunk requests. |
| **Ephemeral Filesystem** (Root filesystem is read-only) | Attempting to write to default `~/.fcc` triggers `OSError: [Errno 30] Read-only file system`. | Dynamic redirect in `paths.py` automatically routes all writable directories to `/tmp/.fcc`. |
| **No Background Processes / Daemon** (Process terminates when HTTP request finishes) | Background threads like long-running file watchers or local subprocesses cannot survive. | Subprocess CLI launchers and background polling loops are disabled in cloud mode. Gateway focus is pure HTTP proxying. |
| **Cold Starts** (Initial request takes 500ms - 2s to initialize Python runtime) | Perceived latency on first request after inactivity. | 1. Lightweight `requirements.txt` with minimal dependencies.<br>2. Module pre-warming in `api/index.py`.<br>3. Fast client startup. |
| **Payload Size Limit** (4.5 MB request body cap on Hobby) | Huge document or file upload payloads might exceed limit. | Clients should stream or truncate oversized contexts. Normal LLM contexts easily fit within 4.5 MB. |
| **Network Socket Inactivity** (Proxy kills idle connections after 15s) | Long inference pauses before first token could disconnect client. | Implemented streaming keep-alive comments in generation loops. |

---

## 3. Unsupported Features in Vercel Cloud Mode
The following desktop-only features are gracefully disabled or omitted in the cloud build:
1. **Desktop GUI Shells:** Tkinter/Qt browser popup (`FCC_OPEN_BROWSER=false`).
2. **Local CLI Subprocess Manager:** Running `claude-code` binaries directly on the Vercel server (Claude Code CLI runs on the user's laptop and connects to FCC Cloud via `ANTHROPIC_BASE_URL`).
3. **Local Ollama / LM Studio on `localhost`:** Local models running on the user's personal laptop cannot be accessed from Vercel's cloud servers unless exposed via a public tunnel (ngrok / Cloudflare Tunnel). Cloud providers (Gemini, OpenAI, Groq, DeepSeek, OpenRouter) work out-of-the-box.
