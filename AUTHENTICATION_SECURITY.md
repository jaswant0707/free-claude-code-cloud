# Authentication & Session Security Specification

## 1. Overview
Free Claude Code Cloud implements cryptographic authentication designed specifically for serverless cloud execution where persistent server memory cannot be assumed across requests.

---

## 2. Stateless Cryptographic Session Tokens

Because Vercel serverless functions spin up and down dynamically across different physical compute nodes, session state cannot reside in local memory dictionaries or single-server session tables.

### Token Architecture
The `fcc_session` token is structured similarly to a lightweight, zero-dependency signed JWT:

$$\text{SessionToken} = \text{Base64Url}(\text{Payload}) \,\|\, \text{"."} \,\|\, \text{Base64Url}(\text{Signature})$$

#### Payload Structure
```json
{
  "email": "jaswanty132@gmail.com",
  "iat": 1740000000,
  "exp": 1740086400,
  "nonce": "4f9b20b2e8117a4d5e9b8675c92841d9"
}
```
- `email`: Normalized lowercase identity of the single owner.
- `iat`: Timestamp of issue (Unix epoch).
- `exp`: Timestamp of expiration (Unix epoch + 86,400 seconds / 24 hours).
- `nonce`: Cryptographically secure random 128-bit hex string ensuring entropy even if issued in the same second.

#### Key Derivation and Signature
Signatures are generated using HMAC-SHA256:
```python
signing_key = hashlib.sha256(f"{OWNER_PASSWORD}:{MASTER_API_TOKEN}".encode("utf-8")).digest()
signature = hmac.new(signing_key, payload_b64.encode("utf-8"), hashlib.sha256).digest()
```
- **Tamper-Proof:** Any change to the email, expiration time, or nonce invalidates the signature.
- **Stateless Verification:** Any serverless container instance with access to the environment variables can verify the token without contacting a database or shared Redis instance.
- **Zero Cost:** No Redis, memcached, or external database required.

---

## 3. Defense-in-Depth Cookie Security

The session cookie is configured with modern defensive attributes:
- `HttpOnly`: Prevents JavaScript access via `document.cookie`, mitigating XSS exfiltration risks.
- `SameSite=Lax`: Defends against Cross-Site Request Forgery (CSRF) on cross-origin requests while enabling smooth navigation when arriving from external bookmarks.
- `Secure`: Set automatically when running over HTTPS (`https://*.vercel.app`) or behind standard cloud reverse proxies (`x-forwarded-proto: https`).
- `Path=/`: Restricts scope to the application root.
- `Max-Age=86400`: Strictly expires the cookie after 24 hours.

---

## 4. Master API Token Specification

The Master API Token (`MASTER_API_TOKEN`) is an independent 256-bit entropy credential used exclusively by developer tools and machine clients:
- Format: High-entropy URL-safe base64 string (minimum 32 characters).
- Storage: Encrypted Vercel Environment Variable.
- Evaluation: Constant-time comparison via `secrets.compare_digest`.
- Protocol Support:
  - Anthropic: `x-api-key: <MASTER_API_TOKEN>` or `Authorization: Bearer <MASTER_API_TOKEN>`
  - OpenAI: `Authorization: Bearer <MASTER_API_TOKEN>`
  - Gemini: `Authorization: Bearer <MASTER_API_TOKEN>` or `x-goog-api-key: <MASTER_API_TOKEN>` or `?key=<MASTER_API_TOKEN>`
