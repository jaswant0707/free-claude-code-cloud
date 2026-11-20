# Cloud Disaster Recovery & High Availability Design

## 1. Resilience Architecture
Because Free Claude Code Cloud runs serverless on Vercel's global edge infrastructure, high availability and disaster recovery are built into the deployment model:

1. **Multi-Zone Serverless Failover:**
   Vercel automatically provisions serverless instances across multiple AWS Availability Zones. If an underlying host node fails, Vercel routes traffic to a healthy instance within milliseconds.
2. **Instant Immutable Rollbacks:**
   Every git commit pushed to `main` creates an immutable Vercel deployment. If a bug is introduced:
   - Rollback to previous deployment in 1 click in Vercel dashboard.
   - Rollback is zero-downtime and instantaneous.
3. **Zero Persistent Host Dependency:**
   Because all configurations are stored as environment variables and sessions are stateless HMAC-SHA256 tokens, instances can be destroyed and recreated at will with zero state corruption.

---

## 2. Emergency Recovery Playbook

### Scenario A: Master API Token or Password Compromise
1. Log in to Vercel Dashboard -> Settings -> Environment Variables.
2. Update `OWNER_PASSWORD` and `MASTER_API_TOKEN` to newly generated secure secrets.
3. Click **Redeploy** on the latest deployment to purge all warm lambdas.
4. Old sessions and compromised tokens are invalidated immediately.

### Scenario B: AI Provider Outage (e.g. Gemini / OpenAI Down)
1. FCC Cloud features automatic model fallback routing.
2. In the Admin Dashboard (`/admin/model_config`), configure secondary fallback providers (e.g. Groq, DeepSeek, OpenRouter).
3. Requests encountering 500/503 from primary provider automatically degrade gracefully to the fallback provider without breaking active developer client connections.

### Scenario C: Vercel Platform Disruption
If Vercel itself experiences regional degradation:
1. The included `Dockerfile` and `docker-compose.yml` allow instantaneous self-hosting on any backup container provider or local Docker daemon:
   ```bash
   docker build -t free-claude-code-cloud .
   docker run -p 8082:8082 --env-file .env.cloud free-claude-code-cloud
   ```
