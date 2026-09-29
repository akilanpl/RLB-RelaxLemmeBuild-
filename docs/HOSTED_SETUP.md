# RLB hosting and account checklist

Implementation is in the existing UEE repository. The authorized non-production Supabase project has been exercised with live Auth/Postgres/Queue/Storage requests. Railway/Vercel deployment and Daytona execution remain blocked; see [verification evidence](ENGINEERING_VERIFICATION.md). No production changes were made.

## Accounts and projects to create or confirm

- [x] Supabase **staging** project, explicitly authorized by its owner. Migrations 001–005 applied; private `workspace-artifacts` bucket created.
- [ ] Supabase **production** project. Never use its credentials in local development or tests.
- [ ] Daytona account, API key, available capacity, and a trusted sandbox image with the Node/Python/build tools supported by your workspaces. Account availability is not yet confirmed.
- [ ] Vercel project connected to this repository, with Root Directory `frontend`. Assign staging/preview and production environment variables separately.
- [ ] Railway project with two services: API and worker. Both build from repository root using `backend/Dockerfile`. Select `railway.api.toml` for the API and `railway.worker.toml` for the worker. Keep staging and production services/secrets separate.
- [ ] At least one supported AI provider account. Configure its credential through RLB's provider settings, then map planner, coder, test_architect, and reviewer roles to workers in a loadout. Provider credentials are encrypted server-side. Never put them in frontend variables.

## Supabase setup

1. For a **new empty** project, apply `schema/supabase_schema.sql`, then every numbered migration in `schema/migrations/` in ascending order (001–005). Commit each script separately. For an existing installation matching the prior RLB schema, back up first and apply only the unapplied additive migrations; do not replay the bootstrap schema over existing data. Inspect schema drift before applying migrations.
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

Known operational limits: local state is memory-only; a separate local worker cannot consume it. Hosted execution still requires a trusted Daytona image and configured provider API model IDs. Private GitHub import and ongoing Git synchronization are unsupported. Published/audit artifacts are deliberately retained indefinitely.

## Provider references

- [Supabase Queues API](https://supabase.com/docs/guides/queues/api)
- [pgmq SQL functions](https://pgmq.github.io/pgmq/api/sql/functions/)
- [Daytona asynchronous Python SDK](https://www.daytona.io/docs/en/python-sdk/async/async-daytona/)
- [Daytona network restrictions](https://www.daytona.io/docs/en/network-limits/)
- [Railway configuration reference](https://docs.railway.com/config-as-code/reference)
- [Vercel build settings](https://vercel.com/docs/deploy-button/build-settings)

## Final engineering pass: migration 003 and readiness

Apply `schema/migrations/003_execution_controls.sql` **after** 001 and 002, including on new installations. It adds durable per-task AI-call accounting, provider attempt records, command evidence, ordered task events, and worker heartbeats. It removes browser write privileges from workflow tables and queue schemas: changes must pass authenticated API authorization/approval checks. The server database role needs table/sequence access and pgmq execution privileges (the usual trusted Supabase `postgres` connection owns these objects). Do not use an `anon` or `authenticated` database role for the worker.

Additional non-secret controls: `MAX_REPAIR_ATTEMPTS=3` and `MAX_TASKS_PER_USER_PER_HOUR=30`. Task submission throttling is per authenticated user; PostgreSQL serializes each user's admission check. Every primary/fallback provider attempt reserves one persisted AI budget unit before the external request. Three transient delivery failures exhaust the worker retry limit. Auth signup/login abuse protection remains Supabase Auth's rate-limit/CAPTCHA/email-confirmation configuration: validate those platform controls in staging; the RLB API does not proxy passwords.

`/health` is process liveness. `/ready` checks hosted database schema, queue existence, a worker heartbeat within 90 seconds, and a private artifact bucket. It returns HTTP 503 when those checks fail. It reports sandbox/provider limitations explicitly, not as successful live execution. API and worker also verify bucket privacy on startup. The worker records its heartbeat every 20 seconds independently of long tasks. Per-user provider readiness still requires configured credentials/loadouts and an actual call.

Daytona sandboxes are deleted after normal execution/cancellation; the SDK request also sets auto-stop at 15 minutes and auto-delete at 60 minutes to bound orphan retention after a process crash. Those settings require live Daytona validation. No image is invented or provided by this repository.



## Engineering completion: migration 004

Apply `schema/migrations/004_artifact_retention.sql` after 003 before starting the updated API/worker. Startup and readiness require its tables. It adds durable cleanup tombstones/progress, fair scan cursors, permanent published-root references and actual fenced queue-delivery counts. Browser roles cannot access these control tables. The trusted server database role must read `storage.objects`; object deletion still uses the existing private Storage service API.

The Railway worker runs retention independently of its consumer: `ARTIFACT_RETENTION_DAYS=7`, `ARTIFACT_CLEANUP_INTERVAL_SECONDS=3600`. Each pass has a 120-second deadline, considers 20 roots and deletes at most 100 objects per root. Canonical/active/published/audit references always win over age. Tombstones are intentionally permanent. Monitor `artifact_cleanup.last_error`, `last_attempt_at`, `completed_at`, `deleted_objects`, plus structured root/error/count logs. Historical snapshots missing root provenance remain protected. Account/legal audit retention should be defined before adding deletion of published evidence.

`MAX_WORKFLOW_STAGE_SECONDS=1800` bounds each active stage (maximum accepted configuration 7200); approval waiting consumes no execution deadline. Delivery recovery is bounded to three actual fenced claims per message. Sandbox deletion calls time out after 30 seconds; provider-side auto-stop/delete remains the crash cleanup backstop and requires live verification.

No new secret is needed. Public GitHub import requires API egress to `codeload.github.com:443`; redirects, arbitrary hosts, authentication and submodules are not supported. No Git subprocess or imported code runs on the API host. Staging validation must confirm real Storage metadata/listing, deletion/retry, publication fencing, and queue recovery with two workers.


## Migration 005, TLS and event delivery

Apply `schema/migrations/005_event_delivery.sql` before deploying this revision. Startup/readiness require version 5. It serializes event insertion per task so a polling cursor cannot skip an uncommitted lower sequence. Command evidence is upserted from running through terminal status; browser polling reads persisted events and authoritative evidence, with a 15-second full-refresh fallback. Logs are bounded/redacted; abrupt process death may leave a running record until task recovery creates a new attempt. Events do not prove command success.

If the PostgreSQL endpoint uses a private CA, configure `DATABASE_SSL_CA_FILE` (mounted public certificate path) **or** `DATABASE_SSL_CA_PEM` (public PEM text) in both Railway services. Obtain the certificate from that project's Supabase Connect/SSL instructions; verify its provenance. These values are not secrets. Hostname and chain verification remain mandatory; do not set `CERT_NONE` or disable SSL. See [Supabase SSL enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement).

Provider worker `model_name` must be an exact API model ID, not a display name such as `Gemini 2.5`. The existing staging settings are preserved. Model availability is account-dependent: validate the selected ID before assigning all four roles. Repair uses the coder mapping and the same durable budget.

## Explicit staging acceptance commands

These opt-in scripts create disposable data, use real external services and clean up their own records. Use **only** the authorized staging configuration. They are excluded from the default automated suite. Secrets stay in the local configuration or platform store; never print/export them through shell tracing.

```sh
ENVIRONMENT=staging DEBUG=false RUN_EMBEDDED_WORKER=false PORT=8001 \
  backend/.venv/bin/python -m backend.serve
```

In a second terminal (set the CA variable if required):

```sh
ENVIRONMENT=staging DEBUG=false RLB_STAGING_APPROVED=1 \
  backend/.venv/bin/python -m scripts.staging_acceptance
# Explicit non-secret model ID required; uses existing encrypted Gemini credential.
ENVIRONMENT=staging DEBUG=false RUN_EMBEDDED_WORKER=false RLB_STAGING_APPROVED=1 \
  RLB_STAGING_MODEL=gemini-3.1-flash-lite \
  backend/.venv/bin/python -m scripts.staging_provider_acceptance
```

`RLB_STAGING_API_URL` defaults to `http://127.0.0.1:8001`; set the authorized Railway staging origin after deployment. The auth script currently reads staging public client settings from `frontend/.env.local` and checks project consistency. Admin-confirmed disposable accounts do not verify the public email-signup journey. The provider script stops before sandbox execution; it does not substitute fake tests for Daytona. Neither command certifies production readiness.

See [operations and recovery](OPERATIONS.md) for backups, restoration, alerting and encryption-key handling.
