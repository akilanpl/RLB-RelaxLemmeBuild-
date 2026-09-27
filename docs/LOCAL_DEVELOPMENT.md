# Local development

Use the existing checkout directly. Node.js 20.9+ and Python 3.11+ are required. Python 3.12 and the installed Node runtime were used for validation.

## Offline backend

From repository root:

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
backend/.venv/bin/python -m backend.local
```

Reuse an existing virtual environment if present. The local launcher clears inherited application configuration, loads `backend/.env.local` if present or `backend/.env.example` otherwise, and forces development mode. It does not load the existing root `.env`. The default API uses memory repositories, local storage, and an embedded worker. `/health` is available at `http://127.0.0.1:8000/health` without a cloud account.

Never place production credentials in `backend/.env.local` or tests. Optional local integration may use a separate test/staging Supabase and Daytona account. With no sandbox credentials, real execution is unavailable and is never reported as passed. In-memory state does not survive restart. Local tests inject deterministic doubles for providers, queue, storage, and sandbox.

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
