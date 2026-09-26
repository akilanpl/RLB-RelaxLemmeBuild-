# Local Development Guide: Cloud AI Software Engineering Workspace

This guide outlines prerequisites, environment configuration, setup steps, and verification procedures for running the workspace stack locally.

---

## 1. Prerequisites

- **Node.js**: v18.0+ or v20+ (tested with v25.9)
- **Python**: v3.11+ or v3.12+ (tested with v3.12)
- **Supabase / PostgreSQL**: Supabase project or local PostgreSQL instance (optional for initial offline health checks, required for persistence)

---

## 2. Repository Structure

```text
project-root/
├── backend/                  # FastAPI backend application
│   ├── .venv/               # Python virtual environment
│   ├── app/
│   │   ├── api/v1/          # REST endpoints
│   │   ├── core/            # Configuration & security
│   │   ├── db/              # Database session, diagnostics, migrations
│   │   ├── models/          # Domain models (Pydantic v2)
│   │   ├── providers/       # Vendor-agnostic AI provider interfaces
│   │   ├── agents/          # Role contracts (Planner, Coder, etc.)
│   │   ├── workflow/        # State machine definitions
│   │   └── sandbox/         # Isolation driver protocols
│   └── tests/               # Backend test suites
├── frontend/                 # Next.js 15 + TypeScript + Tailwind frontend
│   ├── src/
│   │   ├── app/             # Next.js App Router pages
│   │   ├── components/      # Navigation & UI components
│   │   ├── lib/             # API client abstraction
│   │   └── types/           # Shared TypeScript domain contracts
├── docs/                     # Authoritative Phase 0 & engineering docs
└── schema/
    └── supabase_schema.sql  # 27-entity PostgreSQL DDL with RLS
```

---

## 3. Environment Variables

### Backend Configuration (`backend/.env`)
Copy the template:
```bash
cp backend/.env.example backend/.env
```

Key variables:
| Variable | Description | Default |
| :--- | :--- | :--- |
| `PROJECT_NAME` | Application display name | `Cloud AI Software Engineering Workspace` |
| `ENVIRONMENT` | Runtime environment (`development`, `staging`, `production`) | `development` |
| `DEBUG` | Enable debug logging | `true` |
| `API_V1_PREFIX` | Base prefix for v1 API routes | `/api/v1` |
| `BACKEND_CORS_ORIGINS` | JSON list of permitted frontend origins | `["http://localhost:3000"]` |
| `DATABASE_URL` | Supabase PostgreSQL async connection string | `postgresql+asyncpg://postgres:[PASS]@[HOST]:5432/postgres` |
| `SUPABASE_URL` | Supabase project URL | `https://[PROJECT-ID].supabase.co` |
| `SUPABASE_ANON_KEY` | Public anon key | `ey...` |
| `SUPABASE_SERVICE_ROLE_KEY` | Secret backend service role key | `ey...` |
| `CREDENTIAL_ENCRYPTION_KEY` | 32-byte secret for encrypting provider keys | `dev-key-32b-must-be-changed-in-prod` |

### Frontend Configuration (`frontend/.env.local`)
Create `frontend/.env.local` to connect frontend to the FastAPI backend and Supabase Auth:
```bash
cp frontend/.env.example frontend/.env.local
```

Key variables:
| Variable | Description |
| :--- | :--- |
| `NEXT_PUBLIC_API_URL` | Backend FastAPI base URL (default: `http://localhost:8000`) |
| `NEXT_PUBLIC_SUPABASE_URL` | Client-safe public Supabase project URL (`https://[PROJECT].supabase.co`) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Client-safe public Supabase anonymous key (`eyJ...`) |

> [!WARNING]
> NEVER put `SUPABASE_SERVICE_ROLE_KEY` in `frontend/.env.local` or any `NEXT_PUBLIC_*` variable. Only public anon keys are permitted in browser clients.


---

## 4. How to Start the Backend (FastAPI)

1. Activate virtual environment or create one:
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r pyproject.toml  # or install dependencies: fastapi uvicorn pydantic pydantic-settings asyncpg sqlalchemy python-dotenv httpx
```

2. Run development server:
```bash
# From project-root:
backend/.venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

3. Verify backend health:
- Liveness check: `curl http://localhost:8000/health`
- Database diagnostics: `curl http://localhost:8000/health/db`
- Interactive Swagger UI: `http://localhost:8000/api/v1/docs`

---

## 5. How to Start the Frontend (Next.js)

1. Install dependencies:
```bash
cd frontend
npm install
```

2. Run development server:
```bash
npm run dev
```

3. Open in browser:
Visit `http://localhost:3000` to view the Workspace Dashboard and live API connectivity card.

---

## 6. How to Connect Supabase & Setup Auth

1. Create a project in [Supabase Dashboard](https://supabase.com).
2. Go to **Project Settings** > **Database** and copy the **Connection string** (URI).
3. In `backend/.env`, set:
```dotenv
DATABASE_URL="postgresql+asyncpg://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres"
SUPABASE_URL="https://[YOUR-PROJECT-REF].supabase.co"
SUPABASE_ANON_KEY="[YOUR-ANON-KEY]"
SUPABASE_SERVICE_ROLE_KEY="[YOUR-SERVICE-ROLE-KEY]"
```
4. In `frontend/.env.local`, set:
```dotenv
NEXT_PUBLIC_API_URL="http://localhost:8000"
NEXT_PUBLIC_SUPABASE_URL="https://[YOUR-PROJECT-REF].supabase.co"
NEXT_PUBLIC_SUPABASE_ANON_KEY="[YOUR-ANON-KEY]"
```
5. Apply the authoritative schema:
   In Supabase **SQL Editor**, paste and run `schema/supabase_schema.sql` (defines all 27 tables, enums, indexes, Row Level Security policies, and the `on_auth_user_created` trigger).
6. Verify connectivity:
```bash
curl http://localhost:8000/health/db
```
The response will indicate `"connected": true` and report round-trip `latency_ms` without exposing credentials.

### Verifying Workspace Provisioning & Staging (Phase 3)
1. In the authenticated dashboard, click **New Workspace** (`/dashboard/workspaces/new`).
2. Test **Empty Workspace**:
   - Enter name: `demo-empty-repo`
   - Select Environment: `Sandboxed`
   - Select Source: `Empty workspace`
   - Click **Create Workspace**. The workspace appears in status `READY` with `0 files`.
3. Test **ZIP Import**:
   - Create another workspace, select **Upload ZIP**.
   - Choose a project `.zip` archive (up to 25 MB).
   - Click **Create Workspace**. The project structure is extracted into canonical approved storage (`storage/workspaces/{id}/canonical`), and the project file browser loads.
4. Test **Read-Only File Browser**:
   - On `/dashboard/workspaces/[id]`, expand folder nodes and select files.
   - Files are rendered with line numbers and copy controls in strictly read-only mode.
5. Test **Staging Workspace Isolation**:
   - Automated tests in `backend/tests/test_phase3_workspace.py` verify that creating and modifying files in a staging workspace copy NEVER modifies the canonical Approved Workspace files.



---

## 7. Verification Commands

Run full automated checks:

```bash
# 1. Backend tests (Health & Diagnostics)
backend/.venv/bin/pytest backend/tests/

# 2. Python syntax / compile validation
python3 -m py_compile backend/app/main.py backend/app/core/*.py backend/app/db/*.py backend/app/models/*.py

# 3. Frontend TypeScript checks
cd frontend && npm run typecheck

# 4. Frontend Production Build
cd frontend && npm run build
```
