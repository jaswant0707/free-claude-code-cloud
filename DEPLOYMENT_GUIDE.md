# Free Claude Code Cloud — Deployment Guide

This guide details step-by-step instructions for deploying Free Claude Code as a cloud application accessible 24/7 without needing your laptop to stay running.

---

## Architecture Summary

- **Primary Target (Model A):** Vercel Serverless Function (FastAPI / ASGI via `api/index.py`)
- **Secondary Target (Model B):** Docker Container (for unlimited streaming duration or persistent Telegram/Discord bots)
- **Database:** None required (Stateless proxy; ephemeral SQLite in `/tmp` for temporary state)

---

## 1. Primary Deployment: Vercel (Recommended)

Deploying to Vercel gives you a private, zero-maintenance HTTPS deployment with automated SSL and scale-to-zero free-tier pricing.

### Prerequisites
1. A [Vercel account](https://vercel.com).
2. A GitHub account (`jaswant-0707`) with the private repository `free-claude-code-cloud`.
3. At least one AI provider API key (e.g. NVIDIA NIM, OpenRouter, Groq, or Google Gemini).

---

### Step 1: Push Repository to GitHub
Ensure the project is committed to your private GitHub repository:
```bash
git remote add origin https://github.com/jaswant-0707/free-claude-code-cloud.git
git push -u origin main
```

---

### Step 2: Import Project into Vercel
1. Log in to your [Vercel Dashboard](https://vercel.com/dashboard).
2. Click **Add New...** -> **Project**.
3. Select your GitHub repository: `jaswant-0707/free-claude-code-cloud`.
4. In **Project Settings**:
   - **Framework Preset:** Leave as `Other` (or auto-detected).
   - **Root Directory:** `./` (default).
   - **Build Command:** Leave empty.
   - **Output Directory:** Leave empty.

---

### Step 3: Configure Production Environment Variables in Vercel
In the Vercel deployment configuration screen, open the **Environment Variables** section and add the following:

| Variable | Required | Recommended Value / Description |
| :--- | :--- | :--- |
| `FCC_CLOUD_DEPLOYMENT` | **Yes** | `1` |
| `PROXY_AUTH_ENABLED` | **Yes** | `true` |
| `ANTHROPIC_AUTH_TOKEN` | **Yes** | A strong secret token (e.g. generated via `openssl rand -hex 24`). Used by coding agents to authenticate to `/v1/...`. |
| `ADMIN_AUTH_TOKEN` | **Yes** | A strong secret token to access `/admin`. (Can be same or different from `ANTHROPIC_AUTH_TOKEN`). |
| `FCC_CONFIG_DIR` | **Yes** | `/tmp/.fcc` |
| `MODEL` | **Yes** | `nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b` (or your chosen default provider/model) |
| `NVIDIA_NIM_API_KEY` | Optional | Your NVIDIA NIM API key from [build.nvidia.com](https://build.nvidia.com). |
| `OPENROUTER_API_KEY` | Optional | Your OpenRouter API key. |
| `GROQ_API_KEY` | Optional | Your Groq API key. |
| `GEMINI_API_KEY` | Optional | Your Google Gemini API key. |

---

### Step 4: Deploy and Verify
1. Click **Deploy**. Vercel will install dependencies from `requirements.txt` and compile the function.
2. Once complete, you will receive your deployment URL:
   `https://free-claude-code-cloud.vercel.app` (or custom name).
3. **Verify Health Check:**
   ```bash
   curl -i https://your-app.vercel.app/health
   ```
   **Expected Response:** `HTTP/1.1 200 OK`, `{"status": "healthy"}`.
4. **Verify Unauthorized Proxy Rejection:**
   ```bash
   curl -i -X POST https://your-app.vercel.app/v1/messages -H "Content-Type: application/json" -d "{}"
   ```
   **Expected Response:** `HTTP/1.1 401 Unauthorized`.
5. **Verify Authorized Admin Access:**
   Open in your browser:
   `https://your-app.vercel.app/admin?token=<YOUR_ADMIN_AUTH_TOKEN>`
   The Admin UI will open, authenticating your session and setting a secure session cookie!

---

### Step 5: (Optional) Add a Custom Domain
1. In your Vercel Project, go to **Settings** -> **Domains**.
2. Enter your custom domain (e.g. `api.yourdomain.com`).
3. Add the displayed `CNAME` record to your DNS provider (Cloudflare, Namecheap, Route53, etc.).
4. Vercel automatically provisions free, managed SSL/TLS certificates.

---

## 2. Configuring Coding Agents to Use Your Cloud Proxy

Once deployed, you can use your cloud proxy from your laptop, workstation, or remote server without needing local FCC running:

### A. Claude Code CLI
Set environment variables before running Claude Code:
```bash
export ANTHROPIC_BASE_URL="https://your-app.vercel.app/v1"
export ANTHROPIC_AUTH_TOKEN="<YOUR_ANTHROPIC_AUTH_TOKEN>"

# Run Claude Code
claude
```
On Windows PowerShell:
```powershell
$env:ANTHROPIC_BASE_URL = "https://your-app.vercel.app/v1"
$env:ANTHROPIC_AUTH_TOKEN = "<YOUR_ANTHROPIC_AUTH_TOKEN>"
claude
```

### B. Cursor / VS Code / Cline / OpenCode
- **API Base URL / Endpoint:** `https://your-app.vercel.app/v1`
- **API Key / Bearer Token:** `<YOUR_ANTHROPIC_AUTH_TOKEN>`
- **Model:** Any model from your configured providers (e.g. `nvidia/nemotron-3-ultra-550b-a55b` or `anthropic/claude-3.5-sonnet`).

---

## 3. Secondary Deployment: Docker Container (Model B)

If you require persistent Telegram/Discord bots or continuous streaming sessions beyond Vercel's execution limits:

### Run Locally or on a VPS via Docker Compose
1. Create a `.env` file on your server:
   ```env
   FCC_CLOUD_DEPLOYMENT=1
   PROXY_AUTH_ENABLED=true
   ANTHROPIC_AUTH_TOKEN=your-strong-proxy-token
   ADMIN_AUTH_TOKEN=your-strong-admin-token
   MODEL=nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b
   NVIDIA_NIM_API_KEY=nvapi-...
   ```
2. Launch the container:
   ```bash
   docker compose up -d
   ```
3. Check logs:
   ```bash
   docker compose logs -f
   ```

---

## 4. Operational Best Practices & Troubleshooting

| Issue | Cause | Resolution |
| :--- | :--- | :--- |
| **HTTP 401 on /admin** | Missing or incorrect admin token. | Visit `https://your-app.vercel.app/admin?token=<ADMIN_AUTH_TOKEN>` or pass `Authorization: Bearer <ADMIN_AUTH_TOKEN>`. |
| **HTTP 401 on /v1/messages** | Client missing bearer token or api key. | Ensure `ANTHROPIC_AUTH_TOKEN` is passed in client config (`Authorization: Bearer <token>` or `x-api-key: <token>`). |
| **HTTP 504 Gateway Timeout** | Model took >60s to generate response on Vercel Hobby plan. | Upgrade to Vercel Pro (allows 300s `maxDuration`) or deploy via the provided Dockerfile on a container host. |
| **Changes in Admin UI reset** | Ephemeral `/tmp` filesystem in serverless. | For permanent cloud configuration, set provider keys directly in Vercel Project Environment Variables. |
