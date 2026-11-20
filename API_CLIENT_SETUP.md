# Universal API Client Setup: Claude Code, Cursor, Cline, & SDKs

## 1. Overview
Free Claude Code Cloud exposes a universal, multi-protocol AI gateway compatible with Anthropic Messages API, OpenAI Chat Completions API, and Google Gemini API.

---

## 2. Setting Up Official Claude Code CLI

You can point the official `claude-code` CLI tool directly to your private cloud gateway.

### On macOS / Linux / WSL (Bash/Zsh):
```bash
export ANTHROPIC_BASE_URL="https://<your-deployment-url>/v1"
export ANTHROPIC_AUTH_TOKEN="<your-MASTER_API_TOKEN>"
export ANTHROPIC_API_KEY="<your-MASTER_API_TOKEN>"

# Launch Claude Code
claude
```

### On Windows (PowerShell):
```powershell
$env:ANTHROPIC_BASE_URL = "https://<your-deployment-url>/v1"
$env:ANTHROPIC_AUTH_TOKEN = "<your-MASTER_API_TOKEN>"
$env:ANTHROPIC_API_KEY = "<your-MASTER_API_TOKEN>"

# Launch Claude Code
claude
```

---

## 3. Setting Up Cursor IDE

In Cursor Settings -> **Models**:
1. Check **OpenAI API Key** or **Anthropic API Key**.
2. Set **Base URL / Override URL**: `https://<your-deployment-url>/v1`
3. Set **API Key**: `<your-MASTER_API_TOKEN>`
4. Enable your preferred model (e.g. `claude-3-5-sonnet-20241022` or `gemini-2.0-flash`).

---

## 4. Setting Up Cline / Roo Code (VS Code Extension)

1. Open Cline Settings -> **API Provider**.
2. Select **Anthropic Compatible** (or **OpenAI Compatible**).
3. Base URL: `https://<your-deployment-url>/v1`
4. API Key: `<your-MASTER_API_TOKEN>`
5. Model ID: Enter `claude-3-7-sonnet-latest` or `gemini-2.0-pro-exp-02-05`.

---

## 5. Setting Up Python Anthropic SDK

```python
from anthropic import Anthropic

client = Anthropic(
    base_url="https://<your-deployment-url>",
    api_key="<your-MASTER_API_TOKEN>",
)

response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello via Free Claude Code Cloud!"}],
)

print(response.content[0].text)
```

---

## 6. Setting Up cURL (Raw HTTP)

```bash
curl -X POST "https://<your-deployment-url>/v1/messages" \
  -H "Content-Type: application/json" \
  -H "x-api-key: <your-MASTER_API_TOKEN>" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 256,
    "messages": [{"role": "user", "content": "Ping"}]
  }'
```
