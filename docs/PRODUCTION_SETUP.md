# Production setup

Tendr intentionally refuses to start in `APP_ENV=prod` when a core service is
missing. This prevents a deployment that looks healthy but cannot authenticate,
search suppliers, read Goszakup data, or recover analysis jobs.

## Required values

- `POSTGRES_PASSWORD`
- `DATABASE_URL` and `DATABASE_URL_SYNC` (PostgreSQL)
- `REDIS_URL`
- `ANALYSIS_JOB_MODE=redis`
- `ANALYSIS_JOB_STORAGE_DIR` (shared persistent volume for API and worker)
- `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`
- `LLM_API_KEY`
- `GOSZAKUP_API_TOKEN`
- `TAVILY_API_KEY`
- production `ALLOWED_HOSTS` and `ALLOWED_FRONTEND_ORIGINS`

Optional capabilities stay disabled and are reported by
`GET /api/health/capabilities` until their values are added:

- Stripe: `STRIPE_SECRET_KEY`, webhook secret and three price IDs;
- email: SMTP host/from/credentials;
- calls: Leximo token and agent ID;
- monitoring: `SENTRY_DSN`;
- remote page reading: SSH browser settings.

## Start

From the repository root:

```bash
docker compose -f infra/docker-compose.prod.yml up -d --build
```

The compose file runs migrations once, then starts two API workers and a
separate Redis-backed analysis worker. Uploaded analysis files live in a shared
persistent Docker volume. For a multi-host deployment, replace that volume with
a shared object-storage adapter before adding a second host.

## Verify

```bash
curl -fsS http://localhost:8000/api/health
curl -fsS http://localhost:8000/api/health/capabilities
docker compose -f infra/docker-compose.prod.yml ps
```

Never commit `.env`, Supabase secret/service-role keys, SMTP passwords, or API
tokens. The browser receives only the Supabase publishable key.
