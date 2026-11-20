# Environment Variables Reference: Free Claude Code Cloud

This document is the definitive guide to configuring environment variables in Free Claude Code Cloud.

---

## 1. Cloud & Security Configuration (Mandatory for Cloud)

| Variable | Type | Default | Description | Where to Set |
| :--- | :--- | :--- | :--- | :--- |
| `FCC_CLOUD_DEPLOYMENT` | String / Int | `1` in `api/index.py` | Set to `1` or `true` to signal cloud hosting mode. Activates cloud admin security gates and automatic proxy protection. | Vercel Project Settings / Docker ENV |
| `PROXY_AUTH_ENABLED` | Boolean | `true` in cloud | Enforces bearer token authentication for all `/v1/...` API endpoints (`/v1/messages`, `/v1/chat/completions`, etc.). Protects against unauthorized internet traffic. | Vercel Project Settings / Docker ENV |
| `ANTHROPIC_AUTH_TOKEN` | String | `freecc` | Secret token used by coding agents (Claude Code, Cursor, Cline, OpenCode, Aider) to authenticate to the proxy. Supplied as `Authorization: Bearer <token>` or `x-api-key: <token>`. | Vercel Project Settings / Client ENV |
| `ADMIN_AUTH_TOKEN` | String | Falls back to `ANTHROPIC_AUTH_TOKEN` | Secret token required to access the Web Admin UI (`/admin`) and Code Sessions (`/admin/code`). Can be provided via query param `?token=...`, session cookie, or Bearer header. | Vercel Project Settings / Docker ENV |

---

## 2. Storage & Operational Paths

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `FCC_CONFIG_DIR` | Path | `/tmp/.fcc` (serverless) / `~/.fcc` (desktop) | Directory where runtime caches, lockfiles, and ephemeral SQLite databases are written. In serverless environments, this must be within `/tmp`. |
| `LOG_LEVEL` | String | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `LOG_FILE` | Path | `~/.fcc/logs/server.log` | Path for detailed server log file. Defaults to stdout in serverless. |

---

## 3. Model Routing & Fallbacks

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `MODEL` | String | `nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b` | Default model route. Format: `provider_id/model/path`. |
| `MODEL_FABLE` | String | `None` (uses `MODEL`) | Dedicated model route for Claude Code Fable calls. |
| `MODEL_OPUS` | String | `None` (uses `MODEL`) | Dedicated model route for Claude Code Opus calls. |
| `MODEL_SONNET` | String | `None` (uses `MODEL`) | Dedicated model route for Claude Code Sonnet calls. |
| `MODEL_HAIKU` | String | `None` (uses `MODEL`) | Dedicated model route for Claude Code Haiku calls. |
| `MODEL_FALLBACKS` | String | `None` | Custom fallback chains when primary provider encounters rate limits or errors. |

---

## 4. AI Provider API Keys

Set only the API keys for the providers you actively use:

| Provider | Environment Variable | Registration URL |
| :--- | :--- | :--- |
| **NVIDIA NIM** | `NVIDIA_NIM_API_KEY` | [build.nvidia.com](https://build.nvidia.com) |
| **OpenRouter** | `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai) |
| **Groq** | `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) |
| **Google Gemini** | `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) |
| **Together AI** | `TOGETHER_API_KEY` | [api.together.xyz](https://api.together.xyz) |
| **DeepSeek** | `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com) |
| **Cerebras** | `CEREBRAS_API_KEY` | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| **OpenAI** | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| **Mistral AI** | `MISTRAL_API_KEY` | [console.mistral.ai](https://console.mistral.ai) |
| **SambaNova** | `SAMBANOVA_API_KEY` | [cloud.sambanova.ai](https://cloud.sambanova.ai) |
| **Fireworks** | `FIREWORKS_API_KEY` | [fireworks.ai](https://fireworks.ai) |

---

## 5. Client Configuration Examples

### Connecting Claude Code CLI
```bash
export ANTHROPIC_BASE_URL="https://your-deployment.vercel.app/v1"
export ANTHROPIC_AUTH_TOKEN="<your_secret_token>"
claude
```

### Connecting Cursor / Cline / VS Code
- **Base URL:** `https://your-deployment.vercel.app/v1`
- **API Key:** `<your_secret_token>`
- **Model:** `nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b` (or any model supported by your configured providers).
