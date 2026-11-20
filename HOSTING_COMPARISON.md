# Hosting Architecture Evaluation & Comparison

## 1. Hosting Options Evaluated

| Evaluation Criteria | Option 1: Vercel (Selected) | Option 2: Render / Railway | Option 3: VPS (Hetzner / DigitalOcean) |
| :--- | :--- | :--- | :--- |
| **Fixed Monthly Cost** | **$0.00 / month (Free Tier)** | $7.00 - $15.00 / month | $4.00 - $12.00 / month |
| **Laptop Dependency** | **Zero (Runs 24/7 in Cloud)** | Zero | Zero |
| **Scaling & Inactivity** | **Scales to zero (No cost when idle)** | Remains active / charges compute | Continuous billing |
| **Maintenance Burden** | **Zero (Serverless platform managed)** | Low (Container updates) | High (Linux patching, firewall, SSL) |
| **Cold Starts** | 500ms - 1.5s after prolonged idle | Zero (Always-on) | Zero (Always-on) |
| **Max Execution Time** | 60 seconds (Hobby) | Unlimited | Unlimited |
| **Streaming Support** | Supported (Chunked SSE) | Supported | Supported |
| **Security Surface** | Minimal (Read-only ephemeral containers) | Container boundary | Full OS exposure |

---

## 2. Decision Rationale: Why Vercel is the Optimal Choice

1. **Strict Free-First Mandate:**
   The user explicitly required a free-first architecture without incurring unexpected billing. Vercel Hobby provides generous monthly serverless invocations (100 GB-hours, 100k requests/day), which is vastly more than a single developer uses for personal LLM coding workflows.
2. **Single-Project Simplicity:**
   Vercel allows co-hosting the Next-gen Python ASGI backend, static glassmorphic login UI, and admin portal within one git repository and one deployment URL.
3. **Enterprise Edge Security:**
   Automatic TLS, DDoS protection, and encrypted environment variable vaults come standard without configuring Nginx, Certbot, or complex reverse proxies.
