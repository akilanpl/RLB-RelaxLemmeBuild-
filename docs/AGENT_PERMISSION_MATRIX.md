# Agent Permission & Capability Matrix

## 1. Overview and Enforcement Model

To guarantee system security, code integrity, and user safety, every agent executes under an immutable, role-based permission boundary. 

Tools are not registered globally into agent contexts. Instead, the **Agent Permission Gatekeeper** provisions an agent instance with only the exact tool instances authorized for its role. Any invocation of an unauthorized capability throws an immediate runtime exception (`SecurityViolationError`), terminates the agent run, and records an audit incident.

---

## 2. Capability Matrix

| Capability / Tool Scope | PLANNER | CODER | TEST ARCHITECT (Tester 1) | TEST EXECUTOR (Tester 2) | REVIEWER |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Read Approved Workspace Files** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Read Staging Workspace Files** | ❌ | ✅ | ❌ | ❌ | ✅ (via Diff) |
| **Write / Edit Staging Workspace** | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Write / Edit Approved Workspace** | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Propose Unified Code Diff** | ❌ | ✅ | ❌ | ❌ | ❌ |
| **Generate Implementation Plan** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Generate Test Specifications** | ❌ | ❌ | ✅ | ❌ | ❌ |
| **Modify Mandatory Baseline Tests** | ❌ | ❌ | ❌ (Strictly Prohibited) | ❌ (Enforced by Engine) | ❌ |
| **Execute Sandbox Shell Commands** | ❌ | ❌ | ❌ | ✅ (Isolated Sandbox Only) | ❌ |
| **Install Packages / Dependencies** | ❌ | ❌ | ❌ | ✅ (Sandbox Baseline Check) | ❌ |
| **Access Host Network / Filesystem** | ❌ | ❌ | ❌ | ❌ (Air-gapped / Isolated) | ❌ |
| **Inspect Build Logs & Test Results** | ❌ | ✅ (Upon Test Failure) | ✅ | ✅ | ✅ |
| **Switch Loadouts / Workers** | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Approve / Reject Workflow Gates** | ❌ | ❌ | ❌ | ❌ (Human Only) | ❌ |

---

## 3. Role-by-Role Contract & Boundaries

### 1. PLANNER
- **Objective**: Explore the codebase, synthesize requirements, and produce an actionable step-by-step implementation plan.
- **Allowed Tools**:
  - `read_file(path)`: Read contents of approved files.
  - `list_directory(path)`: Explore project tree.
  - `search_codebase(query, pattern)`: Semantic and regex search.
  - `inspect_dependencies()`: Parse `package.json`, `pyproject.toml`, etc.
  - `submit_plan(title, steps, affected_files, risk_assessment)`: Concludes planning phase.
- **Prohibited**:
  - Any file creation, modification, or deletion.
  - Any shell command execution.
  - Bypassing the Human Plan Approval gate.

### 2. CODER
- **Objective**: Implement approved plan changes strictly within an isolated staging environment.
- **Allowed Tools**:
  - `read_file(path)`: Reads from Staging or Approved workspace.
  - `write_staging_file(path, content)`: Creates or overwrites files **in Staging Workspace only**.
  - `edit_staging_file(path, target, replacement)`: Granular edits **in Staging Workspace only**.
  - `delete_staging_file(path)`: Removes files **in Staging Workspace only**.
  - `generate_diff()`: Generates unified git diff of Staging vs Approved.
  - `submit_proposal(diff_summary, commit_message)`: Transitions workflow to Human Code Approval.
- **Prohibited**:
  - Direct file modification in the Approved Workspace.
  - Shell command execution or testing runs.
  - Modifying files unrelated to the approved plan.

### 3. TEST ARCHITECT (Tester 1)
- **Objective**: Author exhaustive test cases based on user request, approved plan, and proposed diff.
- **Allowed Tools**:
  - `read_file(path)`: Read project source and existing tests.
  - `inspect_proposal_diff()`: Review pending changes.
  - `inspect_approved_plan()`: Review agreed-upon architectural design.
  - `submit_test_plan(functional_tests, regression_tests, edge_cases, security_tests)`: Emits test specifications.
- **Prohibited**:
  - Creating, editing, or deleting production code files.
  - Executing test scripts or shell commands.
  - Removing, disabling, or modifying the **Mandatory Baseline Verification Policy**.

### 4. TEST EXECUTOR (Tester 2)
- **Objective**: Execute mandatory baseline verification and Test Architect test cases in an isolated sandbox.
- **Allowed Tools**:
  - `run_sandbox_command(cmd, timeout_seconds)`: Runs command inside isolated container/microVM.
  - `read_sandbox_output(stream_id)`: Fetches stdout/stderr logs.
  - `record_baseline_result(check_type, status, output, exit_code)`: Logs baseline step status.
  - `record_test_result(test_case_id, status, duration_ms, failure_trace)`: Logs individual test result.
  - `emit_failure_report(summary, failed_checks, traces, suggested_remedies)`: Routes loop back to Coder.
- **Prohibited**:
  - Modifying canonical approved source files.
  - Silently skipping or passing failed baseline checks.
  - Escaping the isolated sandbox environment.

### 5. REVIEWER
- **Objective**: Impartial final audit of code, diffs, test results, and execution history.
- **Allowed Tools (Strictly Read-Only)**:
  - `read_file(path)`: Inspect canonical source files.
  - `inspect_project_structure()`: Inspect directories and metadata.
  - `inspect_approved_plan()`: Inspect approved plan document.
  - `inspect_proposed_diff()`: Inspect proposed staging diff.
  - `inspect_test_plan()`: Inspect authored test specifications.
  - `inspect_test_results()`: Inspect pass/fail output from Test Executor.
  - `inspect_build_logs()`: Inspect compile, lint, and type-check logs.
  - `inspect_execution_history()`: Inspect command audit logs and agent run metrics.
  - `inspect_agent_outputs()`: Inspect previous prompts, answers, and rationale.
  - `submit_review_report(summary, score, strengths, concerns, security_audit, final_recommendation)`: Concludes audit.
- **Prohibited (Strict Invariant)**:
  - Writing or editing any files (production, staging, or tests).
  - Executing any shell commands or background tasks.
  - Installing dependencies or running tests.
  - Modifying loadouts or worker configurations.
  - Approving its own review or bypassing human approval gates.

---

## 4. Enforcement Architecture

```mermaid
flowchart TD
    AgentCall["Agent Emits Tool Call"] --> Validator{"Permission Gatekeeper\nCheck(agent_role, tool)"}
    Validator -->|Permitted| WorkspaceCheck{"Target Path Check\n(Staging vs Approved)"}
    Validator -->|Denied| Trap["Security Violation Logged\nAgent Run Aborted"]
    
    WorkspaceCheck -->|Staging Path (Coder)| ExecTool["Execute Tool"]
    WorkspaceCheck -->|Approved Path Write| Trap
    WorkspaceCheck -->|Read-only Path| ExecTool
```
