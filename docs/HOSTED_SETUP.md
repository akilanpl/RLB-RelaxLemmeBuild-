# RLB hosting and account checklist

Implementation is in the existing UEE repository. No cloud projects have been created or deployed by this work. Offline tests exercise the real application services with fake external providers; they do not certify Supabase or Daytona connectivity.

## Accounts and projects to create or confirm

- [ ] Supabase **staging** project, distinct from production. Its existence is not yet confirmed.
- [ ] Supabase **production** project. Never use its credentials in local development or tests.
- [ ] Daytona account, API key, available capacity, and a trusted sandbox image with the Node/Python/build tools supported by your workspaces. Account availability is not yet confirmed.
- [ ] Vercel project connected to this repository, with Root Directory `frontend`. Assign staging/preview and production environment variables separately.
- [ ] Railway project with two services: API and worker. Both build from repository root using `backend/Dockerfile`. Select `railway.api.toml` for the API and `railway.worker.toml` for the worker. Keep staging and production services/secrets separate.
- [ ] At least one supported AI provider account. Configure its credential through RLB's provider settings, then map planner, coder, test_architect, and reviewer roles to workers in a loadout. Provider credentials are encrypted server-side. Never put them in frontend variables.

## Supabase setup

1. For a **new empty** project, apply `schema/supabase_schema.sql`, then `schema/migrations/001_supabase_queue.sql` and `schema/migrations/002_runtime_status_and_rls.sql`. Commit each script separately. For an existing installation matching the prior RLB schema, back up first and apply only the two additive migrations; do not replay the bootstrap schema over existing data. Inspect schema drift before applying migrations.
2. Enable Supabase Queues/pgmq. Migration 001 creates `task_execution` and transactional task-state triggers. Queue messages carry task identifiers, not credentials or source archives. Keep pgmq access server-only; browser clients must not have queue privileges.
3. Create a **private** Storage bucket named `workspace-artifacts`. API and worker use a server service-role key; do not make the bucket public.
4. Obtain the PostgreSQL direct connection or **session pooler** URL on port 5432. Transaction pooling on port 6543 is incompatible with the worker's session advisory locks and is rejected at startup. The database role must be trusted for server-side access.
5. Configure Supabase Auth Site URL and redirect allowlist for the correct Vercel environment. Use supported asymmetric JWT signing (ES256/RS256) and the `authenticated` audience. Local integration uses only a separate test/staging project.
6. Verify signup creates a profile, and two independent users cannot read or modify one another's workspaces, tasks, credentials, or artifacts.

## Required environment variables

Configure secrets in Vercel/Railway secret stores. Do not paste secret values into chat. Public variables are still environment-specific.

| Variable | Service | Value/source | Safe to set before accounts exist? |
|---|---|---|---|
| `ENVIRONMENT` | API + worker | `staging` or `production` | Yes |
| `DEBUG` | API + worker | `false` | Yes |
| `RUN_EMBEDDED_WORKER` | API + worker | `false` | Yes |
| `DATABASE_URL` | API + worker | Secret `postgresql+asyncpg://…` direct/session connection from corresponding Supabase project | Requires Supabase |
| `SUPABASE_URL` | API + worker | Public project API URL | Requires Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | API + worker | Secret server-only key from corresponding Supabase project | Requires Supabase |
| `CREDENTIAL_ENCRYPTION_KEY` | API + worker | Secret URL-safe base64 encoding of 32 random bytes. Same key across API/worker within one environment; different key per environment | Can generate locally into a secret store now |
| `BACKEND_CORS_ORIGINS` | API | JSON list containing exact allowed frontend HTTPS origins | Requires frontend URL |
| `DAYTONA_API_KEY` | worker | Secret Daytona API key | Requires Daytona |
| `DAYTONA_SANDBOX_IMAGE` | worker | Trusted, available container image reference with required runtimes | Requires image selection/Daytona validation |
| `NEXT_PUBLIC_API_URL` | frontend | Public Railway API HTTPS origin, without `/api/v1` | Requires Railway URL |
| `NEXT_PUBLIC_SUPABASE_URL` | frontend | Same environment's public Supabase URL | Requires Supabase |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` **or** `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | frontend | Supabase client-safe anon/publishable key; never the service-role key | Requires Supabase |

Next.js public variables are embedded at build time: rebuild the frontend after changing them. Do not rotate the encryption key without a credential re-encryption procedure; existing encrypted provider credentials depend on it.

## Defaults and optional configuration

These non-secret defaults can be configured now:

| Variable | Default / guidance |
|---|---|
| `SUPABASE_QUEUE_NAME` | `task_execution`; must match the database trigger |
| `SUPABASE_STORAGE_BUCKET` | `workspace-artifacts` |
| `WORKER_POLL_SECONDS` | `1` |
| `DAYTONA_API_URL` | `https://app.daytona.io/api` if omitted/blank |
| `DAYTONA_TARGET` | Optional account-supported region/target |
| `SANDBOX_ALLOWED_DOMAINS` | JSON `["registry.npmjs.org","pypi.org","files.pythonhosted.org"]`; add only domains required by supported builds |
| `MAX_AI_CALLS_PER_TASK` | `20`; persisted agent-run budget also applies across restarts |
| `MAX_AI_OUTPUT_TOKENS` | `8192` |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` |
| `SUPABASE_JWT_ISSUER` | Derived from Supabase URL if omitted |
| `SUPABASE_JWKS_CACHE_TTL_SECONDS` | `3600` |
| `API_V1_PREFIX` | `/api/v1`; keep consistent with frontend |
| `PROJECT_NAME` | Application display name |
| `PORT` | Injected by Railway for API; local default `8000` |
| `SUPABASE_ANON_KEY` | Optional backend public key; not required for server storage/queue |
| `GROQ_API_KEY`, `GROQ_MODEL` | Optional legacy direct-service fallback; durable workflow uses configured provider/loadout roles |
| `RLB_ENV_FILE` | Optional backend env-file path. Hosted services should use platform variables and no bundled secret files |

Sandbox processes receive workspace files and execution limits, not the application's Supabase or provider secrets. Commands execute in Daytona, never through the local API host shell. Package installation may need additional allowed domains for particular dependencies.

## Commands and deployment order

From repository root:

```sh
python3 scripts/check_config.py api
python3 scripts/check_config.py worker
python3 scripts/check_config.py frontend
```

These checks inspect exported variable presence and print **names only**. They do not read `.env`, validate values, or contact services. Hosted startup additionally rejects missing mandatory variables, debug mode, transaction pooling, and a queue name inconsistent with migration 001.

1. Prepare staging Supabase schema, bucket, Auth, Daytona account/image, and provider account.
2. Deploy Railway API (`python -m backend.serve`) and worker (`python -m backend.worker`) as separate processes with matching environment secrets. API healthcheck: `/health`. Worker does not serve HTTP.
3. Deploy Vercel frontend from `frontend`, set its public variables, and set API CORS plus Supabase redirects to its actual URL.
4. Complete staging acceptance below before repeating setup in production.

## Required staging acceptance before production

- [ ] Signup/login/logout and two-user isolation through both API and RLS.
- [ ] ZIP import, file browsing, analysis, configured loadout, plan revision/approval, code diff revision/approval, real sandbox tests, and final review.
- [ ] Restart API and worker during each execution stage. Confirm queued work resumes, review gates remain paused, and one workspace is not executed concurrently by two workers.
- [ ] Confirm queue heartbeat extends visibility during long operations; stopping a worker releases/reclaims its message. Delivery is at least once, so an interrupted AI call can be repeated.
- [ ] Confirm approved artifact snapshots survive process restarts and a failed upload does not change the current canonical pointer.
- [ ] Confirm failed tests display failures, sandbox timeouts fail, missing configuration never appears as a passing test, and network limits apply in real Daytona.
- [ ] Verify private Storage, database role privileges, platform logs, limits, costs, and backup/restore procedures.

Known operational limits: real PostgreSQL/pgmq transactions, cloud promotion SQL, Supabase Storage and Daytona have not been exercised against a live account here. A local PostgreSQL startup was blocked by the execution environment's shared-memory restriction. Sandbox output is collected per completed command, not streamed live. Failed uploads can leave unreferenced snapshot objects; automated retention/garbage collection is not implemented. Local in-memory mode loses workflow data when restarted. The full authenticated browser journey requires test Supabase and provider configuration.

## Provider references

- [Supabase Queues API](https://supabase.com/docs/guides/queues/api)
- [pgmq SQL functions](https://pgmq.github.io/pgmq/api/sql/functions/)
- [Daytona asynchronous Python SDK](https://www.daytona.io/docs/en/python-sdk/async/async-daytona/)
- [Daytona network restrictions](https://www.daytona.io/docs/en/network-limits/)
- [Railway configuration reference](https://docs.railway.com/config-as-code/reference)
- [Vercel build settings](https://vercel.com/docs/deploy-button/build-settings)
