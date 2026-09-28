# Engineering verification — 2026-09-28

Scope: existing `/Users/akilan/Downloads/UEE`, branch `feat/engineering-complete`, based on PR #2 (`41dd45e`). No visual redesign. Existing root `.env` values were inspected for presence only and intentionally not used, per the owner's instruction. No cloud migration, deployment, AI request or Daytona call was made.

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
safely; published versions are retained. Interrupted copies leave unreferenced objects eligible for the worker retention sweep.

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

Final local backend suite: 161 tests. The expected duplicate-ZIP fixture warning remains. Frontend lint, type checking and production build are required alongside the suite.

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

The owner intentionally excluded the available Supabase/Daytona accounts. `DAYTONA_SANDBOX_IMAGE` remains unspecified. Supabase migrations have not been applied. Local PostgreSQL initialization is blocked by shared-memory permissions; the dedicated CI job tests migration 004 and retention queries against disposable PostgreSQL. Supabase Auth signup/refresh/RLS permissions, real pgmq locking/recovery, transaction commit failure, private Storage behavior, Daytona limits/orphan deletion, real provider requests, and browser reconnect during a hosted task require a separately authorized staging pass.

Apply migrations 001 through 004 in order (bootstrap schema first only for a new empty database). Configure the private bucket, isolated test accounts, model loadouts, and trusted Daytona image. Validate Supabase Auth rate limits/CAPTCHA/email policy. `/ready` is actionable infrastructure readiness, not proof that every user's provider account can execute or that Daytona has completed a command.

## Engineering completion additions

IMPLEMENTED / LOCALLY VERIFIED: restart-safe artifact deletion ledger, bounded hourly worker cleanup, immutable import publication, import concurrency fencing, bounded upload reads, GitHub public branch archive import, safe API error responses, workflow stage deadlines, sandbox cleanup deadlines, terminal failure persistence, and retry accounting that excludes queue lock contention. Approval waits reset local delivery budgets. Task-linked discarded staging stays available as audit bytes.

Cleanup defaults to seven days, 20 prefixes and 100 objects per prefix per pass, with a 120-second pass deadline. It uses the Storage API for deletion, never SQL deletion from `storage.objects`. Workspace locks exclude active workers/imports. Canonical, active-task, published and task-linked audit trees are retained indefinitely. Tombstones prevent a retired prefix from being published later; failed deletions retry after restart. Scan timestamps prevent protected roots starving later candidates. Legacy snapshots with incomplete provenance are conservatively retained.

Public import accepts only `https://github.com/owner/repo` and an explicit branch (default `main`). Downloads use the fixed codeload host, no credentials/proxies/redirects, size/time bounds, and existing ZIP/path validation. Private repositories, submodules and other Git hosts are explicitly unsupported. This is a snapshot import, not ongoing Git synchronization. The existing form now calls the import endpoint and reports failures instead of treating Git selection as a successful empty project.

STAGING VERIFIED: none. NOT VERIFIED: live Supabase/Auth/pgmq/Storage, Daytona, external providers, Railway and Vercel. The PostgreSQL CI job is an isolated retention/migration contract test, not a substitute for those checks.

KNOWN LIMITATIONS: command output is delivered after each command; local state is memory-only; authenticated browser acceptance needs authorized staging credentials. Audit artifacts deliberately have no automatic deletion policy. Legacy ambiguous roots require explicit future audit/retention decisions. No UI redesign was performed.

This pass is locally verified engineering hardening. It is not a claim of hosted or production acceptance.
