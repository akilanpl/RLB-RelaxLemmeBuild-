# Engineering verification — 2026-09-28

Scope: existing `/Users/akilan/Downloads/UEE`, branch `feat/final-hosted-product`, based on `7732ab2`. No visual redesign. Existing root `.env` values were inspected for presence only and intentionally not used, per the owner's instruction. No cloud migration, deployment, AI request or Daytona call was made.

## Runtime

`backend/app/services/runtime.py` is the application composition root. API and worker entrypoints resolve it independently. Module-level compatibility references are lazy and allocate no adapters on import. Hosted startup validates configuration, hydrates provider configuration, and rejects a public artifact bucket. Hosted API cannot start an embedded worker; the Railway worker composes Daytona through the existing driver and SDK bridge.

Local API uses an embedded worker, memory repositories/queue and local storage. Those repositories are deliberately not durable across process termination. A separate local worker cannot consume that queue. Deterministic tests inject fake providers/sandbox into real services; normal browser mode has no fake login or simulated successful AI execution.

One transition policy lives in `workflow/states.py`. The browser/API path persists
`analyzing`, `staging_setup`, and `promoting` as worker stages. Human code approval
stores the selected proposal ID atomically with the transition to `promoting`;
a fresh worker resumes promotion from that record. Staging copy and promotion no
longer depend on the approval HTTP request staying alive. Existing synchronous
service helpers retain composite transitions for legacy integrations/tests, but
the browser path uses durable stages. Failed unpublished uploads can be removed
safely; published versions are retained. Interrupted staging copies can leave
unreferenced objects requiring retention cleanup.

## Local acceptance covered

- ZIP fixture import, repository analysis, planning, plan approval, staging-only coding, diff, code approval, immutable local promotion, generated tests, deliberate failure, bounded repair, second approval, retest, review and completion.
- Worker reconstruction against retained test repositories; existing lease expiration, duplicate claim and post-persistence retry tests. These are deterministic service recovery checks, not live PostgreSQL or OS-crash certification.
- 429/5xx/timeouts fall back; 400/401 do not. Each attempt reserves persisted task budget before the external call, with per-attempt identity, outcome, latency and token evidence.
- Finite delivery retries, cancellation of an active stage, task admission limits, finite repair limits, and exhausted-budget rejection after service reconstruction.
- Two-user HTTP/service checks for workspace/files/tasks/history/events/agent runs/tests/proposals/loadouts/credentials and approval/promotion mutations; JWT algorithm/issuer/audience/expiry tests in the existing suite.
- Zero-exit timeout still fails verification and invokes sandbox cleanup. Missing configuration is unavailable, not passed. Command results are recorded individually, including sandbox/task/execution IDs, timestamps, command, exit code and bounded redacted logs.
- Concurrent local promotion accepts one approval; previous canonical content remains intact. Cloud upload failure never enters its pointer transaction.
- Hosted configuration fails closed before allocating local fallback adapters. Root `.env` is excluded from explicit test launches.

## Checks

Final local backend suite: 133 tests. The expected duplicate-ZIP fixture warning remains. Frontend lint, type checking and production build are required alongside the suite.

Run from repository root:

```sh
RLB_ENV_FILE=backend/.env.example backend/.venv/bin/python -m pytest backend/tests -q
backend/.venv/bin/python -m pip check
git diff --check
```

Run in `frontend`:

```sh
npm run lint
npm run typecheck
NEXT_PUBLIC_SUPABASE_URL= NEXT_PUBLIC_SUPABASE_ANON_KEY= NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY= npm run build
```

Process smoke: `python -m backend.local` serves `/health`, `/ready` and API documentation. With no provider configured, the embedded worker processes an imported fixture through analyzing/planning then fails explicitly; a second user receives HTTP 403. Standalone `backend.worker` rejects memory mode as intended.

## Future staging acceptance — not run

The owner intentionally excluded the available Supabase/Daytona accounts. `DAYTONA_SANDBOX_IMAGE` remains unspecified. Migration 003 has not been executed against PostgreSQL. Supabase Auth signup/refresh/RLS permissions, real pgmq locking/recovery, transaction commit failure, private Storage behavior, Daytona limits/orphan deletion, real provider requests, and browser reconnect during a hosted task require a separately authorized staging pass.

Apply migrations 001, 002 and 003 in order (bootstrap schema first only for a new empty database). Configure the private bucket, isolated test accounts, model loadouts, and trusted Daytona image. Validate Supabase Auth rate limits/CAPTCHA/email policy. `/ready` is actionable infrastructure readiness, not proof that every user's provider account can execute or that Daytona has completed a command.

Residual limits: command output is returned after each command rather than streamed live; old and orphaned artifact snapshots have no scheduled garbage collector; local state is memory-only; the full browser journey needs real test authentication. Repository sync by Git URL is not implemented; ZIP and file import are the supported ingestion paths.

This pass is locally verified engineering hardening. It is not a claim of hosted or production acceptance.
