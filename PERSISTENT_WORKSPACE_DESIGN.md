# Persistent Workspace Design: Ephemeral Storage vs External State

## 1. Context & Motivation
Traditional desktop Free Claude Code instances rely on `$HOME/.fcc/` to store SQLite history, cached provider models, and custom credentials. In cloud hosting, treating the local disk as permanent causes silent state loss or deployment failures due to read-only constraints.

---

## 2. Stateless Core Architecture

Free Claude Code Cloud treats **the gateway as 100% stateless**:
1. **Model & Provider Configuration:**
   - Injected via environment variables (`GEMINI_API_KEY`, `DEFAULT_MODEL`, etc.).
   - Initialized at startup and cached per warm lambda instance.
2. **Session Authentication:**
   - Stateless HMAC-SHA256 signed cookies. Zero session tables in database.
3. **API Keys:**
   - Encrypted at rest in Vercel environment settings, never written to disk.

---

## 3. Ephemeral Workspace Storage (`/tmp/.fcc`)

For temporary operational needs during request execution, FCC Cloud allocates state to the ephemeral container directory `/tmp/.fcc`:
- SQLite WAL mode is configured with ephemeral pragmas:
  ```sql
  PRAGMA journal_mode = MEMORY;
  PRAGMA synchronous = OFF;
  PRAGMA temp_store = MEMORY;
  ```
- Any data written to `/tmp` serves strictly as a temporary scratchpad.

---

## 4. Optional External Persistence (When Required)

If persistent chat transcript storage across months is desired in future phases without paying for databases:
1. **GitHub Gist / Repository Storage (Free):** Transcripts can be committed periodically via GitHub API.
2. **Supabase Free Tier (PostgreSQL):** Direct connection via Supabase client only if structured analytics or multi-device code sessions are explicitly enabled.
3. **Current Recommendation:** Omit Supabase. The primary utility of FCC Cloud is high-speed model proxying and AI tool execution (Claude Code / OpenClaw), where clients store conversation history locally on the developer's laptop while the heavy LLM translation happens in the cloud.
