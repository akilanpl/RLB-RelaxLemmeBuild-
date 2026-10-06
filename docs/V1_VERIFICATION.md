# RLB V1 implementation verification

Verified on 2026-10-06 on macOS arm64. This is implementation evidence, not Windows or hosted deployment certification.

## Implemented boundaries

- Existing local workflow and agents retained: task, Planner, human plan approval, Coder, human code approval, Test Architect, real Test Executor, repair/code approval, Reviewer, completion.
- SQLite persists plans, proposals, staging metadata, encrypted provider configuration, testing/review evidence, quotas, worker state, command receipts and pending events. Interrupted executions are cancelled evidence; runnable tasks recover on startup.
- Local promotion journals immutable approved intent before selected-folder writes. Restart completes partial approved publication. Stopped/failed tasks remain terminal and do not start tests; conflicting external edits remain intact and are reported in task messages.
- Existing device control now supports authenticated task review artifacts and versioned plan/code decisions. Command ownership, task/device association, durable receipts and idempotency remain enforced. Device events catch up after network loss independently of local execution.
- Desktop release uses protected paired ownership, per-launch local authorization, encrypted persistent provider secrets, isolated ports and sandboxed renderer IPC. Development impersonation and environment overrides are excluded from this release path.
- Tests execute in disposable immutable snapshot copies with bounded output, minimal environment and process-tree cancellation. Python dependency installation uses a disposable virtual environment. The existing local process driver has the user's OS permissions; it does not provide an OS container or network firewall.
- Hosted control-only deployment uses `RLB_CONTROL_PLANE_ONLY=true`, forbids hosted execution mutations/worker startup, and publishes control/observability. Optional existing hosted execution is preserved when this setting is false.

## Checks

From the repository root:

```sh
RLB_ENV_FILE=backend/.env.example backend/.venv/bin/python -m pytest backend/tests backend/integration backend/hosted_integration -q --tb=short
backend/.venv/bin/python -m compileall -q backend scripts
git diff --check
cd frontend
npm run lint
npm run typecheck
npm run build
cd ../desktop
npm run check
npm run build:all
```

Backend: 242 passed; two disposable PostgreSQL integration tests skipped. The sole warning is the deliberately duplicated ZIP security fixture. The 31 V1 integration/security cases cover restart at both gates, real failed execution and repair, provider configuration encryption/reconstruction, remote review artifacts and approvals, stale/cross-owner rejection, interrupted execution records, terminal publication recovery/conflicting external edits, prompt gate handling, local subprocess secret isolation/cancellation, release authentication, URL/path validation, and control-only behavior. Existing suites cover pause/resume persistence, offline outbox catch-up, and command replay.

Frontend lint/typecheck/production build, Python compile checks, Electron syntax/startup tests (9 passed), frontend desktop contract tests (2 passed), and whitespace checks pass. `build:all` produces the standalone frontend and frozen sidecar on this host. Frozen sidecar process checks cover desktop-mode authorization, local registration and provider/workspace persistence after process restart. Electron’s actual bundled Node runtime also served the standalone frontend, authenticated readiness nonce, setup page and static JavaScript successfully.

## External acceptance gates

1. Windows x64 installer: run `npm run dist` in `desktop` on Windows, install on a clean Windows user account, pair to the intended hosted deployment, and run the complete approval/repair/control/restart scenario with actual provider credentials.
2. Disposable PostgreSQL/pgmq: run the existing retention and hosted-runtime integration suites against separate clean databases. This macOS host rejects PostgreSQL shared-memory creation (`shmget: Operation not permitted`), and has no pgmq extension/container runtime.
3. Intended live hosted deployment/account: apply the repository migrations through 008, configure the private artifacts bucket and JWT authentication, enable control-only mode, and exercise actual browser authentication, pairing, remote review/artifacts/controls, and network-loss recovery. No live hosted database was mutated during these checks.
