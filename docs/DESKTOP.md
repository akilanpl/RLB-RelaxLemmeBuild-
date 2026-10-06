# Windows desktop and remote control

## Runtime boundaries

- The Windows runtime owns project files, task execution, the embedded worker,
  local SQLite state, and execution through the local process driver.
- Electron starts the local FastAPI sidecar and packaged Next.js standalone
  frontend on independent available loopback ports. The API binds to `127.0.0.1`; the
  window is hidden on close and execution remains active until tray-menu quit.
- The frontend port is selected per launch, not fixed at 3000. Only that exact
  loopback origin is added to local API CORS and local-token checks.
- User data lives below Electron's per-user application-data directory (on
  Windows, `%APPDATA%\rlb-desktop`):
  `data/rlb.sqlite3`, `data/device-connection.sqlite3`, and `logs/desktop.log`.
- Hosted PostgreSQL/Supabase/Daytona adapters remain separate and optional.

## Device control API

User requests authenticate with the existing Supabase access token. The web
app obtains a five-minute one-time pairing token with
`POST /api/v1/devices/pairings`. The device exchanges it once at
`POST /api/v1/devices/pair`, supplying platform/version/capability metadata.
The device credential is returned once; the server stores only its SHA-256
digest. Device requests use that credential as a bearer token at
`/api/v1/device-session/heartbeat`, `/commands`, and `/disconnect`.

Authenticated users can list/detail/revoke only their own devices, create
idempotent remote commands, and inspect command history. The server derives the
owner from verified auth or from the paired device record; browser-supplied
ownership IDs are not trusted. Hosted deployments must apply migration 006
(device control), migration 007 (stable event cursors), and migration 008
(task artifact metadata); the device/command/artifact tables have RLS and
server-only grants.

The local `DeviceConnectionManager` uses outbound HTTPS polling, heartbeat, and
acknowledgement. It records command receipts locally, reports interrupted
commands as failures rather than executing them a second time, and reconnects
with exponential backoff. Desktop pairing configures it at runtime; for
headless local development it can also be enabled by setting
`RLB_CONTROL_PLANE_URL` and `RLB_DEVICE_TOKEN` in the local runtime
configuration. Local execution does not wait for this connection.

Tasks, gates, staging/proposals, test plans/executions, reviews, provider/loadout settings, AI accounting, queue controls, and pending prompts survive process restart. Interrupted runs are recorded as cancelled and runnable work is reconciled with the queue. Promotion commits an immutable intent before modifying the selected project; recovery accepts only original or approved file hashes and preserves unexpected external edits.

Task events are committed to the local SQLite outbox before upload. The
connection manager retries unacknowledged events after reconnect, while the
host assigns per-device cursors for ordered web catch-up. Event payloads carry
task/workspace identifiers and state, not project file contents.

The command router reuses the local queue/workflow for starting tasks, safe
pause/resume at workflow-stage boundaries, stopping tasks, and routing prompts
to Planner/Coder stages. Prompts are rejected at human approval gates.
Arbitrary shell commands are not a remote command type. `REVIEW_TASK` uploads a private JSON review bundle through the existing artifact API. `PLAN_DECISION` and `CODE_DECISION` carry the reviewed task version and plan/proposal ID, supporting approval, rejection, and revision through the existing local workflow. Stale evidence cannot authorize a later gate. Heartbeats advertise local project IDs/names without absolute paths or project source, allowing the web to select projects registered on that PC.

## Local project folders and artifacts

In the desktop app, **New workspace** opens the native Electron folder picker;
the web renderer cannot supply an arbitrary filesystem path through that picker
API. The selected path is retained in the per-user local SQLite registry.
Registration and refresh create a local snapshot under application data for
the existing staging/review workflow; they do not upload the project snapshot
to hosted storage. If a staging database is explicitly configured for local
development, workspace and file metadata (including relative paths, hashes,
counts, and the sanitized Git remote) is mirrored there for existing task and
workspace records; file contents and the selected absolute folder path remain
local. Git metadata is informational, and embedded HTTP credentials are
removed from displayed remote URLs.

Snapshot scanning skips symlinks/reparse-point directories and common generated
folders (`.git`, dependency directories, caches, and build outputs), with
limits of 5,000 files and 100 MiB total content. Task creation refreshes the
selected folder first. Approved changes are written back only if the source
folder still matches the task's base snapshot; concurrent external edits cause
the promotion to fail rather than be overwritten.

Task artifacts are distinct from workspace snapshots. The device uploads
individual, task-linked files over the authenticated device API; each file is
capped at 25 MiB and hosted metadata expires according to
`ARTIFACT_RETENTION_DAYS` (seven days by default). Hosted cleanup removes expired
private-storage objects and retains cleanup metadata for retries. Artifact
downloads are authenticated and scoped to the owning user/device/task.

## Development and packaging

Run the Electron shell with `cd desktop && npm install && npm start`. In
development it starts the local API and Next.js dev server. Install
`backend/requirements-desktop.txt` to provide PyInstaller.

On a Windows x64 build host, `cd desktop && npm run dist` builds Next.js
standalone output, collects the Python runtime into a sidecar directory, and
generates an x64 NSIS installer. Packaged execution uses Electron's bundled
Node runtime for the Next standalone server and does not require separately
launched npm or Python processes. This macOS build host cannot validate or
produce the Windows Python sidecar/installer; installation, startup, recovery,
and uninstall must be smoke-tested on Windows.

Device pairing begins in the signed-in web app, where an owner creates a
short-lived one-time token. In the desktop app, open **Pair this desktop** and
enter that token plus the control-plane API URL. Electron exchanges it directly
with the control plane and stores the long-lived device credential with
Electron `safeStorage` in the per-user application-data directory; the secret
is not returned to the renderer or written to `config.env`. `safeStorage` uses
the operating system's credential protection facilities. If the credential
cannot be unlocked, startup fails explicitly instead of silently reconnecting
without authentication. The app's local API token is generated for each
launch and is not shared with the frontend server process. A separate one-time
readiness nonce is passed to the frontend server and required by Electron
before it exposes privileged renderer IPC.

## Execution and release boundary

The packaged sidecar uses `ENVIRONMENT=desktop`: local access is bound to the paired owner and the per-launch local token; the development `x-user-id` path and manual agent-stage endpoints are disabled. The provider encryption key is random and protected by Electron safeStorage. Both server ports are selected at startup and the API URL is obtained through trusted renderer IPC, so a frontend build-time URL cannot route local execution to the cloud.

Tests execute in disposable copies of the immutable approved snapshot. Python dependencies use a disposable virtual environment. Project subprocesses receive a minimal environment without RLB/cloud/provider credentials, bounded output, and process-tree cancellation/timeout cleanup. This existing local process driver runs with the Windows user's OS permissions; it is not an OS container or a network firewall. The project's Git/Node/Python toolchains must be installed as needed. Hosted Daytona isolation remains optional.

## Remaining validation and limitations

- A live hosted device session has not been verified from this environment.
- The 32-step end-to-end remote-control scenario, including live pairing,
  remote commands, event catch-up, and artifact transfer, has not been run
  against a hosted account.
- Windows installer generation and Windows-specific runtime behavior,
  including install/upgrade/uninstall, code signing, and crash recovery, have
  not been validated from this macOS build host.

Stop cancels test process trees and prevents subsequent stages. An approved file publication already in progress finishes its durable publication boundary before stop takes effect; recovery completes that approved publication without starting tests for a stopped task. External edits that conflict with a recovery are preserved and reported in task messages. Interrupted test executions retain cancelled evidence.
