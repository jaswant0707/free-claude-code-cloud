# Security Audit & Threat Modeling: Free Claude Code Cloud

**Audit Date:** November 2026  
**Security Lead:** Senior Security Engineer  
**Scope:** `free-claude-code-cloud` Application, API Boundaries, Authentication, and Cloud Ingress  

---

## 1. Executive Summary

A comprehensive, defense-in-depth security audit was conducted on Free Claude Code to evaluate its suitability for public/private cloud hosting. In its original upstream state, the application was intended for local machine usage only (`localhost`). When exposed to cloud environments, several high-severity security exposures were identified and systematically resolved prior to deployment readiness:

1. **Loopback-Only Hardcoding:** Admin endpoints previously rejected all remote IPs with 403, preventing secure remote administrative access.
2. **Open Proxy Risk:** Proxy authentication was disabled by default (`PROXY_AUTH_ENABLED=False`), leaving upstream LLM credits vulnerable to theft by external internet crawlers.
3. **Missing Security Headers:** Responses lacked standard defensive HTTP headers.
4. **Credential Exposure Risk:** Lack of strict `.gitignore` patterns risked committing `.env` files or SQLite databases containing credentials.

All identified risks have been mitigated and verified through automated test suites.

---

## 2. Threat Analysis & Vulnerability Remediation Matrix

| Vulnerability / Threat | Severity | Upstream State | Cloud Remediated State | Verification Status |
| :--- | :--- | :--- | :--- | :--- |
| **Unauthenticated API Proxying (LLM Resource Theft)** | **Critical** | `proxy_auth_enabled=False` by default. Anyone with network access could route queries. | Enforced automatically when deployed in cloud or when auth token is configured. | **VERIFIED** (Automated tests reject unauthenticated requests with 401). |
| **Admin UI Internet Exposure** | **Critical** | Hardcoded loopback IP check (`client_host == 127.0.0.1`), rendering remote access impossible or requiring total firewall bypass. | Replaced with `require_cloud_admin` checking constant-time Bearer tokens, secure session cookies, or bookmark tokens. | **VERIFIED** (Automated tests reject unauthorized access; authorized sessions work). |
| **Timing Attacks on Authentication** | **Medium** | Potential string equality check vulnerabilities. | All authentication token validations utilize constant-time `secrets.compare_digest`. | **VERIFIED** (Source code inspected and tested). |
| **Session Hijacking / CSRF** | **Medium** | No cookie configuration for admin access. | Cookies configured with `HttpOnly`, `SameSite=Lax`, and `Secure` attributes. | **VERIFIED** (Response headers tested in `test_cloud_deployment.py`). |
| **Clickjacking & MIME-Sniffing** | **Low** | Absence of defensive headers. | Added pure ASGI `SecurityHeadersMiddleware` attaching `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and `Referrer-Policy`. | **VERIFIED** (Present in all HTTP responses). |
| **Credential Leakage in Git** | **High** | Basic `.gitignore` missing modern secret extensions and `.vercel` cache. | Hardened `.gitignore` excluding all `.env*`, `.vercel`, `*.db`, certificates, and keyfiles. | **VERIFIED** (Git status checked, zero sensitive files tracked). |

---

## 3. Defense-in-Depth Mechanisms

### 3.1 Dual-Token Authentication Gate
- **Client Traffic (`/v1/...`):** Guarded by `ANTHROPIC_AUTH_TOKEN`. Clients authenticate via `Authorization: Bearer <token>` or Anthropic `x-api-key: <token>` or Google `x-goog-api-key: <token>`.
- **Administrative Traffic (`/admin/...`):** Guarded by `ADMIN_AUTH_TOKEN`. Protects settings, model selection, and credentials. Supports initial navigation token (`?token=...`), which securely issues a session cookie for all subsequent UI actions.

### 3.2 Secret Masking and Leak Prevention
- In the Admin API (`GET /admin/api/config`), API keys stored in configuration are masked (`MASKED_SECRET = "********"`). Plaintext keys are never returned across the wire to the frontend.
- Loguru logging filters out raw authorization headers and keys from request traces.

### 3.3 Ephemeral Cloud Storage
- The application redirects all write operations (`paths.py`) to `/tmp/.fcc`. In serverless cloud execution (Vercel), no sensitive configuration files remain on a persistent shared disk.

---

## 4. Residual Risks & Recommended Cloud Settings

1. **Vercel Deployment Protection:**
   - Even with application-level authentication, we recommend enabling **Vercel Password Protection** or **Deployment Protection** in the Vercel Dashboard for projects that do not require public webhook access.
2. **Environment Variable Storage:**
   - Store all API keys exclusively in Vercel's encrypted Environment Variables console. Never write them into local files before pushing.
