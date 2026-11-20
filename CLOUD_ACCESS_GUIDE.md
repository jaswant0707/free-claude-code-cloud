# Cloud Access & Owner Onboarding Guide

## 1. Quick Start: Accessing Your Cloud Workspace

Once deployed to Vercel, your private deployment URL will look like:
`https://free-claude-code-cloud.vercel.app` (or your custom domain).

---

## 2. Web Browser Access (Owner Workspace)

### Step 1: Open Deployment URL
Open `https://<your-deployment-url>/` in any web browser (desktop, tablet, or smartphone).
- Unauthenticated visitors are automatically redirected to `https://<your-deployment-url>/login`.

### Step 2: Authenticate with Owner Credentials
- Enter your configured `OWNER_EMAIL`.
- Enter your configured `OWNER_PASSWORD`.
- Click **Sign In**.

### Step 3: Admin & Workspace Navigation
Upon successful authentication:
- A secure `fcc_session` cookie is attached.
- You are redirected to `/admin` where you can:
  - Configure AI providers (Gemini, OpenAI, Anthropic, DeepSeek, Groq, etc.).
  - Select default models and fallback sequences.
  - Review live token usage, rate limits, and latency metrics.
  - Inspect code sessions.

### Step 4: Secure Logout
Click **Logout** in the navigation bar or send a `POST /api/auth/logout` request. The session cookie is immediately deleted.

---

## 3. Remote Access from Anywhere
Because the application is hosted in the cloud on Vercel:
- Your local Windows laptop **does NOT need to stay turned on**.
- You can access the Admin UI from your phone or any workstation globally.
- Developer tools (Claude Code CLI, OpenClaw, Cursor) can communicate with your cloud gateway 24/7.
