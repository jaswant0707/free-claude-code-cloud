# OpenClaw Integration Guide: Free Claude Code Cloud

## 1. Overview
OpenClaw is an autonomous agent framework and GitHub repository manager that connects to LLM backends via the standard Anthropic Messages protocol or OpenAI Chat Completions protocol.

By integrating OpenClaw with Free Claude Code Cloud, you can run autonomous repository audits, code reviews, and PR generation in the cloud without exposing high-cost direct API keys to third-party scripts.

---

## 2. Configuration Architecture

```
+-------------------+              +-------------------------------+              +--------------------+
|  OpenClaw Agent   |  HTTP/SSE    | Free Claude Code Cloud        |  HTTPS API   | LLM Provider       |
|  (GitHub Action / | -----------> | (Vercel Serverless Gateway)   | -----------> | (Google Gemini /   |
|   Local Runner)   | x-api-key    | Translates, routes & streams  | Provider Key |  DeepSeek / Groq)  |
+-------------------+              +-------------------------------+              +--------------------+
```

---

## 3. Environment Variables for OpenClaw

Set the following environment variables in your OpenClaw execution environment (or GitHub Actions Secrets):

```bash
# Gateway Base URL
export ANTHROPIC_BASE_URL="https://<your-deployment-url>/v1"

# Master API Authentication Token
export ANTHROPIC_API_KEY="<your-MASTER_API_TOKEN>"
export ANTHROPIC_AUTH_TOKEN="<your-MASTER_API_TOKEN>"

# Selected Model Route (Transparently routed to your configured provider in FCC)
export OPENCLAW_MODEL="claude-3-5-sonnet-20241022"
```

---

## 4. GitHub Actions Workflow Integration Example

To run OpenClaw autonomously in CI/CD using your private cloud gateway:

```yaml
name: OpenClaw Autonomous Review

on:
  pull_request:
    types: [opened, synchronize]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run OpenClaw Review via FCC Cloud
        env:
          ANTHROPIC_BASE_URL: ${{ secrets.FCC_CLOUD_URL }}/v1
          ANTHROPIC_API_KEY: ${{ secrets.FCC_MASTER_API_TOKEN }}
        run: |
          npx openclaw review --pr ${{ github.event.pull_request.number }}
```

---

## 5. Streaming and Tool Calling Verification
- **Tool Calling:** OpenClaw passes function calling tool schemas in the Anthropic format (`tools: [...]`). FCC Cloud automatically converts these schemas to upstream provider formats (Gemini function declarations or OpenAI tool calls) and maps responses back seamlessly.
- **Thinking Blocks:** If `REASONING_EFFORT` or thinking models are selected, FCC Cloud formats the `<thinking>` blocks appropriately for OpenClaw.
