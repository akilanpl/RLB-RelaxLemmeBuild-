# Engineering Conventions & Standards

## 1. Architectural Integrity & Path Conventions

1. **Path Agnosticism**:
   - All architecture specifications, code comments, and documentation must reference the generic path `project-root/`.
   - Local, host-specific, or machine-specific file paths (e.g. `/Users/...`, `C:\...`) are strictly prohibited in documentation and codebase assets.
2. **State Ownership Rule**:
   - Workspaces own files, tasks, conversations, plans, and diffs.
   - LLM models and workers are transient, stateless compute engines. Never store task context or memory inside worker objects.

---

## 2. Strong Typing & Contract Parity

1. **Backend Typing (Python 3.11+)**:
   - Strict Pydantic v2 schemas for all API inputs, outputs, domain entities, and agent tool parameters.
   - Abstract base classes and protocols (`typing.Protocol`, `abc.ABC`) for extensibility (e.g., `BaseProviderAdapter`, `BaseSandboxDriver`).
   - Zero tolerance for untyped `dict` or `Any` in API request/response signatures.
2. **Frontend Typing (TypeScript 5+)**:
   - Strict type-checking (`strict: true`, `noImplicitAny: true`).
   - Frontend types in `src/types/` must maintain 1:1 structural alignment with backend Pydantic models.
3. **Database Typing (PostgreSQL DDL)**:
   - All identifiers in snake_case.
   - Primary keys must use `UUID PRIMARY KEY DEFAULT gen_random_uuid()`.
   - Timestamps must always use `TIMESTAMPTZ DEFAULT NOW()`.

---

## 3. Agent Safety & Security Guidelines

1. **Least-Privilege Tool Access**:
   - Agents must only receive tools explicitly permitted by the `AGENT_PERMISSION_MATRIX.md`.
   - Reviewer is strictly read-only. Reviewer has zero file-writing, command-execution, dependency-installing, or loadout-switching capabilities.
   - Planner is strictly read-only.
   - Test Architect cannot edit production source code.
2. **Staging Isolation for Coder**:
   - Coder write/edit/delete tools must be physically and logically restricted to the `staging_workspace` path.
   - Approved workspace files are read-only to Coder during code generation.
   - Only human approval triggers atomic promotion of the staged diff into the approved workspace.
3. **Secrets & Credentials Management**:
   - Provider API keys must be encrypted using AES-256-GCM before database insertion.
   - API keys must never be logged, printed to console, or returned in any REST/SSE payload to the browser.
4. **Isolated Sandbox Execution**:
   - All shell commands executed by the Test Executor must execute inside an ephemeral sandbox (gVisor/Docker microVM).
   - Network access is disabled or strictly allowlisted. Resource limits (CPU, memory, disk quotas) are non-negotiable.

---

## 4. Test Verification Invariants

1. **Mandatory Baseline Verification**:
   - Test Executor must always execute the 6-step baseline check before running Test Architect test cases:
     1. Dependency install validation
     2. Static type check
     3. Lint check
     4. Production build
     5. Baseline unit & integration tests
     6. Basic application startup / health check
   - Neither Test Architect nor any configuration setting can bypass or remove this baseline suite.
2. **Failure Loop**:
   - When a baseline check or custom test fails, Test Executor must emit a structured `FailureReport` with exact commands, exit codes, and stack traces, and route back to Coder.

---

## 5. Auditability & Immutability

1. **Immutable Audit Trails**:
   - Records in `agent_runs`, `approvals`, `build_results`, `test_executions`, and `git_snapshots` are append-only.
   - Modifications (`UPDATE`) to historical audit logs are prohibited by database schema and RLS policies.
2. **Provenance Logging**:
   - Every `agent_run` must capture `worker_id`, `provider_id`, `model_name`, `started_at`, `completed_at`, `fallback_used`, `fallback_reason`, and `execution_status`.
