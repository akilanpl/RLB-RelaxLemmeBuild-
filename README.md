# RLB — Relax, Lemme Build

An AI engineering workspace with explicit plan and code approval, isolated test
execution, and an evidence-based final review.

## Local development

Requires Python 3.12 and Node.js 20.9+ (Node 22 recommended).

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
backend/.venv/bin/python -m backend.local
```

The local launcher ignores project-root secrets and uses `backend/.env.example`
unless you create `backend/.env.local` with staging-only credentials. Without
cloud configuration, the API starts with local storage and an in-process queue.
AI generation and sandbox execution report missing configuration honestly.

In a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Use only staging Supabase public configuration in `frontend/.env.local`.
Without it, the landing page loads and authentication reports its setup requirement.
Do not copy production credentials into local development.

## Checks

```sh
backend/.venv/bin/python -m pytest backend/tests -q
cd frontend
npm run lint
npm run typecheck
npm run build
```

## Hosting

Vercel serves the frontend. Railway runs separate API and worker services.
Supabase provides PostgreSQL, Auth, private Storage, and Queue. Daytona executes
project commands in isolated sandboxes. All services share the existing interfaces.

See [deployment and account checklist](docs/HOSTED_SETUP.md) for environment
variables, migrations, platform settings, and the remaining live staging checks.
