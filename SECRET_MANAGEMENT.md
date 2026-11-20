# Secret Management Policy & Guidelines: Free Claude Code Cloud

## 1. Zero-Trust Credential Standard
Under no circumstances should production credentials, owner passwords, master tokens, or third-party AI provider keys be committed to source code or stored in unencrypted configuration files.

---

## 2. Secrets Inventory

| Environment Variable | Description | Security Level | Recommended Rotation Period |
| :--- | :--- | :--- | :--- |
| `OWNER_EMAIL` | Single owner identity | Low (Public identifier) | As needed |
| `OWNER_PASSWORD` | Single owner dashboard password | Critical (Zero-Knowledge) | 90 days or upon compromise |
| `MASTER_API_TOKEN` | Gateway master key for AI clients | Critical | 180 days or upon compromise |
| `GEMINI_API_KEY` | Google Gemini API Key | High | Provider managed |
| `OPENAI_API_KEY` | OpenAI API Key | High | Provider managed |
| `ANTHROPIC_API_KEY`| Anthropic Claude API Key | High | Provider managed |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | High | Provider managed |
| `GROQ_API_KEY` | Groq API Key | High | Provider managed |
| `OPENROUTER_API_KEY`| OpenRouter API Key | High | Provider managed |

---

## 3. Deployment Configuration in Vercel

### Step-by-Step Vercel Secrets Setup:
1. Navigate to the Vercel Dashboard -> **free-claude-code-cloud** project.
2. Select **Settings** -> **Environment Variables**.
3. Add the key-value pairs selecting **Production** and **Preview** environments.
4. Ensure **Automatically expose System Environment Variables** is kept default.
5. All variables are automatically encrypted at rest using AES-GCM-256 by Vercel.

---

## 4. Compromised Credential Handling
If any credential was previously shared in logs, test outputs, or unencrypted channels:
1. Consider the previous value compromised immediately.
2. Generate a new high-entropy secret using OpenSSL or Python:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
3. Update the value in Vercel Environment Variables.
4. Trigger a production redeployment to instantly purge old lambda instances.
5. Never paste secrets into chat or public issue trackers.
