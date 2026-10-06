# Local development

Use the existing checkout directly. Node.js 20.9+ and Python 3.11+ are required. Python 3.12 and the installed Node runtime were used for validation.

## Offline backend

From repository root:

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
backend/.venv/bin/python -m backend.local
```

Reuse an existing virtual environment if present. The local launcher clears inherited application configuration, loads `backend/.env.local` if present or `backend/.env.example` otherwise, and forces development mode. It does not load the existing root `.env`. Development mode uses SQLite at `storage/local-runtime/rlb.sqlite3`, local filesystem storage, the local Windows execution driver, and an embedded worker. Tasks and queued jobs survive API restarts; an interrupted lease is reclaimed on the next startup. `/health` is available at `http://127.0.0.1:8000/health` without a cloud account.

Never place production credentials in `backend/.env.local` or tests. Optional local integration may use a separate test/staging Supabase and Daytona account. Local execution uses disposable copies of the approved snapshot and requires the project toolchains (for example Git, Node/npm, and Python) on PATH. No Daytona account is required for local execution; AI stages require configured provider credentials and loadout mappings. Tests continue to use explicit in-memory doubles unless a persistence test opts into SQLite. Hosted mode continues to use PostgreSQL/Supabase and Daytona.

## Frontend

In `frontend` run `npm ci`, then `npm run dev`. Configure `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`. Browser authentication requires client-safe credentials from a separate test Supabase project. The app can render without them, but signup/login and the complete authenticated product journey are unavailable. Do not overwrite an existing `.env.local` blindly; inspect variable names and preserve user settings without sharing secret values.

For a preview without configured cloud auth, explicitly clear its public Supabase variables:

```sh
NEXT_PUBLIC_SUPABASE_URL= NEXT_PUBLIC_SUPABASE_ANON_KEY= NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY= npm run dev
```

## Validation

From repository root:

```sh
backend/.venv/bin/python -m pytest backend/tests -q
backend/.venv/bin/python -m pip check
```

From `frontend`:

```sh
npm run lint
npm run typecheck
npm run build
npm audit
```

The offline backend suite does not require production infrastructure. Never set `USE_REAL_DATABASE_IN_TESTS=1` with a production database. Cloud integration and authenticated browser acceptance remain separate from these checks.

## Hosted environments

See [HOSTED_SETUP.md](HOSTED_SETUP.md) for the exact account/env checklist, additive migrations, and deployment acceptance steps. Vercel runs the frontend; Railway runs API and worker separately; Supabase supplies Auth/PostgreSQL/Queue/private Storage; Daytona supplies isolated execution. Local and hosted implementations share the existing abstractions.

## Deterministic engineering smoke test

From the existing repository root, without using root `.env` accounts:

```sh
RLB_ENV_FILE=backend/.env.example backend/.venv/bin/python -m pytest backend/tests/test_final_engineering.py -q
```

This includes the real ZIP import, analysis, workflow, approval, versioned promotion, deliberate test failure, bounded repair, review and completion services. Only provider/sandbox infrastructure is replaced with explicit deterministic doubles. Fixtures live in `backend/tests/fixtures/rlb-fixture`; imported project commands are never executed on the test host. Restart checks reconstruct workers/services over retained test repositories; they do not prove process-crash durability of Supabase.

For the local API, the embedded worker shares the SQLite queue. Do not start a second process over the same local database: the local queue is checkpointed by one embedded worker. Electron enforces a single application instance.

For a credential-free frontend preview:

```sh
cd /Users/akilan/Downloads/UEE/frontend
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 NEXT_PUBLIC_SUPABASE_URL= NEXT_PUBLIC_SUPABASE_ANON_KEY= NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY= WATCHPACK_POLLING=true npm run dev -- --hostname 127.0.0.1 --port 3000
```

## Desktop development and Windows packaging

From the repository root, install the optional packaging dependency and
Electron development dependencies:

```sh
backend/.venv/bin/python -m pip install -r backend/requirements-desktop.txt
cd desktop
npm install
npm start
```

The Electron development shell starts the existing local backend and Next.js
frontend, binds the API to loopback, and moves SQLite, workspace storage, and
logs under Electron's per-user application-data directory. Closing the window hides it; use the tray
menu's explicit quit command to stop the processes. The Electron main process
creates a per-launch local API token and injects it only into the renderer
preload bridge.

### Registering a local project

In the desktop shell, choose **New workspace → Local project folder** and use
the native folder picker. The local runtime validates and scans the selected
folder, excludes symlinks and common generated directories, and stores the
workspace-to-folder mapping alongside the local SQLite runtime state. The
workspace remains available after restart; its file snapshot is refreshed from
the registered folder when a task is created. Human-approved code snapshots
are then written back inside that folder; if the folder changes while a task is
in progress, promotion is rejected rather than overwriting those changes. Git
branch, origin URL, and a working-tree summary are recorded when Git is
available. The existing task workflow and approval gates are used; local folder
selection does not create a separate workspace or task system.

On Windows, `npm run dist` builds Next.js standalone output, packages the
Python sidecar with PyInstaller, and creates an NSIS installer. The packaged
frontend and runtime launch without separately starting npm or Python. Build
the installer on Windows; cross-platform Windows packaging is not validated.
Packaged builds use `ENVIRONMENT=desktop`, ignore development `config.env`, and refuse hosted database/service-role credentials or development identity headers. SQLite is stored in the user-data `data` subdirectory and logs in `logs`. Provider keys are encrypted with a random key protected by Electron safeStorage.

Create a one-time pairing token in the signed-in web app and enter it in the desktop setup page. The protected pairing identity gives the desktop local access without a browser JWT refresh or cloud connection. Device commands, event catch-up, private artifacts, and remote approval gates are connected through the existing APIs in `docs/DESKTOP.md`. Do not place a production
device token in source control or frontend variables.

The web control plane uses real Supabase signup/login. The desktop uses its securely stored paired account identity and per-launch local API token; it does not use a development login bypass. Local AI calls require an available provider; temporary control-plane loss does not block local workflow execution. An unavailable AI provider is retried within the persisted budget and cannot fabricate passing results.
