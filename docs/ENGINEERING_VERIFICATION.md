# Engineering verification — 2026-09-29

Scope: existing `/Users/akilan/Downloads/UEE`, branch `feat/final-non-ui-completion`, based on merged PR #3 (`a37a36c`). No visual redesign. The owner explicitly authorized the existing non-production Supabase project and staging provider credentials. Production was not accessed or changed.

## IMPLEMENTED

Existing architecture is preserved: independent API/worker composition, durable workflow/approval gates, provider/loadout abstraction, bounded retries/AI budgets, immutable promotion, Daytona sandbox driver, artifact retention and public GitHub/ZIP import.

This pass adds:

- Persisted running/terminal command evidence, bounded stdout/stderr callbacks through Daytona sessions, command IDs and idempotent evidence updates. Cancellation/disconnect cannot become a passing result. Project commands never execute on the API/worker host.
- Migration 005: per-task event insertion locks prevent a browser cursor skipping an uncommitted earlier event. Database/evidence remains authoritative; browser polling resumes from persisted state and falls back to full refresh every 15 seconds.
- Explicit PostgreSQL TLS CA configuration with hostname verification, connection/query deadlines and hidden SQL parameters.
- Explicit pgmq parameter types fix acknowledgement ambiguity in staging and visibility-update ambiguity with pgmq 1.10 in CI.
- Per-worker output-token ceilings applied to provider requests, including fallback workers.
- Opt-in staging acceptance scripts and disposable real-PostgreSQL/pgmq integration/backup-restore CI coverage.

## LOCALLY VERIFIED

167 backend tests passed (one expected duplicate-ZIP fixture warning), `pip check`, frontend lint/typecheck/production build and `git diff --check`. Local tests use `backend/.env.example`, excluding cloud credentials.

Coverage includes deterministic import → analysis → planner → human plan approval → staging coding → diff → human code approval → immutable promotion → tests → deliberate failure → bounded repair → second approval → retest → reviewer → completion. Tests also cover cancellation, queue duplication/retry limits, concurrent approval/promotion, upload failure, invalid archives, tenant isolation, JWT issuer/audience/algorithm/expiry, transient 429/5xx/timeouts, non-transient auth failures and durable budget exhaustion.

New regressions cover command cancellation evidence, bounded separate streams, cleanup after stream failure, command-result idempotency, worker token limits and verified TLS. Daytona SDK session behavior is tested with an injected SDK double; it is not live Daytona certification.

```sh
RLB_ENV_FILE=backend/.env.example backend/.venv/bin/python -m pytest backend/tests -q
backend/.venv/bin/python -m pip check
git diff --check
cd frontend
npm run lint
npm run typecheck
NEXT_PUBLIC_SUPABASE_URL= NEXT_PUBLIC_SUPABASE_ANON_KEY= NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY= npm run build
```

The `postgres-runtime` CI job uses a disposable PostgreSQL server with the real pgmq extension. It applies bootstrap/migrations and verifies claim/heartbeat/duplicate fencing/reclaim/ack, concurrent approvals, command SQL/event ordering and RLS, followed by a dump/restore rehearsal. The separate retention integration job validates deletion/publication transactions. These jobs do not stand in for managed cloud or browser acceptance.

## STAGING VERIFIED

Through a local HTTP API backed by the authorized real staging services:

- Supabase migrations 001–005 applied; private `workspace-artifacts` bucket created. Existing `workspace-files` bucket and existing user workspaces were preserved.
- Two disposable admin-confirmed users: actual password login, refresh, JWT-authenticated API access, logout and persisted task/session access across an API process restart.
- ZIP import into private Storage and durable task/workspace records.
- Cross-user denial for workspaces/files/content/analysis, tasks/events/history/runs/plans/test plans/executions/proposals/permissions and approval mutation. Direct REST RLS denial/isolation for workspaces/tasks/events/files/runs/test executions/proposals/loadouts/credentials; private artifact denial for the foreign user.
- Readiness correctly reported database/queue/storage ready and HTTP 503 with a stale worker heartbeat; no missing worker was presented as healthy.
- Actual pgmq: enqueue, claim, heartbeat/visibility extension, duplicate workspace fencing, disconnected-client lease reclaim and acknowledgement. This is live queue-client recovery, not a Railway worker crash test.
- Actual PostgreSQL: command-result upsert and running/success events; concurrent entity event insertion blocks until the earlier task event commits.
- Actual private Storage/retention: canonical protection, orphan discovery/deletion, restart idempotence, preserved canonical bytes and rejection of publication into a retired prefix. The disposable fixture used zero-day expiry; production defaults remain seven days.
- Real Gemini `gemini-3.1-flash-lite` planner, coder and Test Architect passed through persisted disposable worker/loadout configuration and the existing encrypted credential. Concurrent plan approval allowed one winner; code approval and immutable promotion passed against actual PostgreSQL/Storage. Provider attempt/token accounting was verified. Existing display-label worker configurations were preserved; they require valid API IDs before normal use. Earlier invalid-label/unsupported-model/transient provider attempts failed explicitly without false success.

Disposable users/workspaces/objects were removed. Safe summaries were written locally to `/tmp/rlb-staging-acceptance-report.json`, `/tmp/rlb-retention-acceptance-report.json` and `/tmp/rlb-provider-acceptance-report.json`. No keys or generated private project content are included in these reports.

## PRODUCTION VERIFIED

None. No production migrations, configuration, deployments or data operations were performed. RLB is **not certified production-ready**.

## NOT VERIFIED / external gates

- `DAYTONA_SANDBOX_IMAGE` is absent from available staging configuration. No image was invented and no Daytona API call was made. Live execution, network restrictions, cleanup/auto-delete, timeout/cancellation and sandbox crash behavior remain unverified.
- No Railway/Vercel project link, CLI login or deployment token was available. Internet-facing API/worker/frontend deployment, exact hosted CORS/redirects and browser refresh/reconnect during a running cloud task remain unverified.
- Public signup requires email confirmation. Admin-provisioned disposable accounts do not verify delivery/confirmation, signup abuse controls or a full browser login journey.
- Real repair/reviewer-after-test acceptance and the complete hosted golden workflow remain open: no test evidence was fabricated to bypass the missing Daytona image.
- Managed Supabase backup/PITR and Storage-byte restoration have not been exercised. The installed local pg_dump 15 client cannot dump staging PostgreSQL 17. A mode-0600 public-data/function/policy snapshot was saved before migrations; it is explicitly **not** a full disaster-recovery backup. See [operations](OPERATIONS.md).

## KNOWN LIMITATIONS

The desktop runtime persists tasks, approval gates, queue controls/prompts, staging metadata, proposals/diffs, test evidence, reviewer reports, provider/loadout configuration, and AI accounting in SQLite. Only one process may own a local runtime; use its embedded worker. See V1_VERIFICATION.md for the current local-first validation; the earlier hosted results above remain historical evidence. There is no fake browser login or fake passing AI/sandbox workflow. Private GitHub imports, submodules, other Git hosts and ongoing Git synchronization remain explicitly unsupported; secure private access needs a separately designed tenant credential flow.

Published/task-linked audit artifacts and ambiguous legacy roots are conservatively retained; audit deletion policy is owner-controlled. Abrupt worker death can leave a running command record; recovery creates a new attempt and never infers success. At-least-once delivery can repeat an interrupted provider call, subject to persisted budget. External staging gates above still require completion before a production readiness decision.
