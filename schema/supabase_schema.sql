-- =============================================================================
-- Cloud-Based AI Software Engineering Workspace Database Schema
-- Supabase / PostgreSQL DDL with Row-Level Security (RLS)
-- Total Entities: Exactly 27 Relational Tables
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Enums
CREATE TYPE environment_mode AS ENUM ('sandboxed', 'connected');
CREATE TYPE workspace_status AS ENUM ('provisioning', 'ready', 'import_failed', 'archived');
CREATE TYPE agent_role_type AS ENUM ('planner', 'coder', 'test_architect', 'test_executor', 'reviewer');
CREATE TYPE task_status AS ENUM (
    'idle', 'analyzing', 'ready', 'planning', 'plan_review', 
    'staging_setup', 'coding', 'code_review', 'staging_cleanup',
    'promoting', 'test_planning', 'test_executing', 'reviewing', 
    'completed', 'cancelled', 'failed', 'repairing'
);
CREATE TYPE approval_status AS ENUM ('pending', 'approved', 'rejected', 'revision_requested');
CREATE TYPE execution_status AS ENUM ('queued', 'running', 'completed', 'failed', 'timeout', 'cancelled', 'success', 'retryable_error', 'blocked', 'rate_limited', 'not_applicable');
CREATE TYPE baseline_check_type AS ENUM (
    'dependency_install', 'type_check', 'lint', 
    'production_build', 'unit_integration_tests', 'health_check'
);

-- 1. USERS
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    display_name TEXT,
    avatar_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. PROVIDERS
CREATE TABLE providers (
    id TEXT PRIMARY KEY, -- 'groq', 'gemini', 'openrouter', 'custom'
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    supports_streaming BOOLEAN NOT NULL DEFAULT TRUE,
    supports_tool_calling BOOLEAN NOT NULL DEFAULT TRUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. CREDENTIALS
CREATE TABLE credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE RESTRICT,
    encrypted_api_key TEXT NOT NULL,
    key_fingerprint TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_provider UNIQUE (user_id, provider_id)
);

-- 4. WORKERS
CREATE TABLE workers (
    id TEXT PRIMARY KEY, -- e.g. 'worker-groq-llama-70b'
    provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE RESTRICT,
    model_name TEXT NOT NULL,
    context_window_tokens INTEGER NOT NULL,
    max_output_tokens INTEGER NOT NULL,
    temperature NUMERIC(3, 2) NOT NULL DEFAULT 0.20,
    rate_limit_rpm INTEGER,
    rate_limit_tpm INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5. LOADOUTS
CREATE TABLE loadouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE, -- NULL for system presets
    name TEXT NOT NULL,
    description TEXT,
    is_system_preset BOOLEAN NOT NULL DEFAULT FALSE,
    mappings JSONB NOT NULL, -- Map of agent_role -> {primary_worker_id, fallback_worker_ids}
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. WORKSPACES
CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    environment_mode environment_mode NOT NULL DEFAULT 'sandboxed',
    status workspace_status NOT NULL DEFAULT 'ready',
    canonical_root_path TEXT NOT NULL,
    file_count INTEGER NOT NULL DEFAULT 0,
    total_size_bytes BIGINT NOT NULL DEFAULT 0,
    current_snapshot_hash TEXT,
    git_remote_url TEXT,
    is_archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_workspace_slug UNIQUE (user_id, slug)
);

-- 7. STAGING_WORKSPACES
CREATE TABLE staging_workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    task_id UUID, -- Logical reference to tasks(id), nullable for infrastructure staging
    staging_root_path TEXT NOT NULL,
    base_snapshot_hash TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    discarded_at TIMESTAMPTZ
);

-- 8. WORKSPACE_SETTINGS
CREATE TABLE workspace_settings (
    workspace_id UUID PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
    active_loadout_id UUID REFERENCES loadouts(id) ON DELETE RESTRICT,
    sandbox_cpu_limit NUMERIC(4, 2) NOT NULL DEFAULT 2.00,
    sandbox_memory_limit_mb INTEGER NOT NULL DEFAULT 4096,
    sandbox_timeout_seconds INTEGER NOT NULL DEFAULT 600,
    auto_analyze_on_import BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 9. FILES
CREATE TABLE files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    file_type TEXT NOT NULL, -- 'file', 'directory'
    size_bytes BIGINT NOT NULL DEFAULT 0,
    sha256_hash TEXT NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_workspace_file_path UNIQUE (workspace_id, relative_path)
);

-- 10. FILE_METADATA
CREATE TABLE file_metadata (
    file_id UUID PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
    language TEXT,
    ast_summary JSONB,
    imports JSONB,
    exports JSONB,
    line_count INTEGER NOT NULL DEFAULT 0,
    is_test_file BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 11. CODEBASE_ANALYSES
CREATE TABLE codebase_analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    analysis_version INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(32) NOT NULL DEFAULT 'completed', -- 'pending', 'running', 'completed', 'failed', 'stale'
    source_snapshot_hash TEXT,
    summary TEXT NOT NULL,
    primary_languages JSONB NOT NULL DEFAULT '[]',
    frameworks_detected JSONB NOT NULL DEFAULT '[]',
    technologies JSONB NOT NULL DEFAULT '[]',
    dependencies JSONB NOT NULL DEFAULT '[]',
    entry_points JSONB NOT NULL DEFAULT '[]',
    dependency_graph JSONB NOT NULL DEFAULT '{}',
    warnings JSONB NOT NULL DEFAULT '[]',
    indexed_files JSONB NOT NULL DEFAULT '[]',
    architecture_overview TEXT NOT NULL DEFAULT '',
    analysis_duration_ms INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- 12. CONVERSATIONS
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'Engineering Session',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 13. MESSAGES
CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender_type TEXT NOT NULL, -- 'user', 'agent', 'system'
    agent_role agent_role_type,
    content TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 14. TASKS
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_prompt TEXT NOT NULL,
    -- Denormalized orchestration fields used by the application contract.
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    objective TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    approved_snapshot_hash TEXT,
    status task_status NOT NULL DEFAULT 'idle',
    active_loadout_id UUID NOT NULL REFERENCES loadouts(id) ON DELETE RESTRICT,
    worker_overrides JSONB, -- Optional temporary overrides for this task
    active_staging_workspace_id UUID REFERENCES staging_workspaces(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 15. AGENT_RUNS
CREATE TABLE agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_role agent_role_type NOT NULL,
    loadout_id UUID REFERENCES loadouts(id) ON DELETE RESTRICT,
    worker_id TEXT REFERENCES workers(id) ON DELETE RESTRICT,
    provider_id TEXT REFERENCES providers(id) ON DELETE RESTRICT,
    model_name TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
    fallback_reason TEXT,
    initial_worker_id TEXT REFERENCES workers(id) ON DELETE SET NULL,
    execution_status execution_status NOT NULL DEFAULT 'running',
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    error_message TEXT
);

-- 16. AGENT_STATES
CREATE TABLE agent_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_role agent_role_type NOT NULL,
    state_payload JSONB NOT NULL,
    checkpoint_seq INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_task_agent_seq UNIQUE (task_id, agent_role, checkpoint_seq)
);

-- 17. PLANS
CREATE TABLE plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_run_id UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    steps JSONB NOT NULL,
    affected_files JSONB NOT NULL,
    risk_assessment TEXT,
    revision_number INTEGER NOT NULL DEFAULT 1,
    structured_plan JSONB NOT NULL DEFAULT '{}',
    source_snapshot_hash TEXT,
    status TEXT NOT NULL DEFAULT 'pending_review',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 18. APPROVALS
CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    gate_type TEXT NOT NULL, -- 'plan_approval', 'code_approval'
    status approval_status NOT NULL DEFAULT 'pending',
    user_feedback TEXT,
    reviewed_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

-- 19. CODE_PROPOSALS
CREATE TABLE code_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_run_id UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    staging_workspace_id UUID NOT NULL REFERENCES staging_workspaces(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    commit_message TEXT NOT NULL,
    revision_number INTEGER NOT NULL DEFAULT 1,
    base_snapshot_hash TEXT,
    status TEXT NOT NULL DEFAULT 'ready_for_review',
    impact JSONB NOT NULL DEFAULT '{}',
    warnings JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 20. DIFFS
CREATE TABLE diffs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_proposal_id UUID NOT NULL REFERENCES code_proposals(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    diff_type TEXT NOT NULL, -- 'added', 'modified', 'deleted'
    unified_diff TEXT NOT NULL,
    additions_count INTEGER NOT NULL DEFAULT 0,
    deletions_count INTEGER NOT NULL DEFAULT 0,
    before_content TEXT NOT NULL DEFAULT '',
    after_content TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 21. TEST_PLANS
CREATE TABLE test_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_run_id UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    plan_summary TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 22. TEST_CASES
CREATE TABLE test_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_plan_id UUID NOT NULL REFERENCES test_plans(id) ON DELETE CASCADE,
    category TEXT NOT NULL, -- 'functional', 'regression', 'edge_case', 'security'
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    expected_result TEXT NOT NULL,
    test_code TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 23. TEST_EXECUTIONS
CREATE TABLE test_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_run_id UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    all_passed BOOLEAN NOT NULL DEFAULT FALSE,
    total_tests INTEGER NOT NULL DEFAULT 0,
    passed_tests INTEGER NOT NULL DEFAULT 0,
    failed_tests INTEGER NOT NULL DEFAULT 0,
    execution_duration_ms INTEGER NOT NULL DEFAULT 0,
    failure_report JSONB, -- Structured failure report when loopback to coder is needed
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 24. BUILD_RESULTS
CREATE TABLE build_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_execution_id UUID NOT NULL REFERENCES test_executions(id) ON DELETE CASCADE,
    check_type baseline_check_type NOT NULL,
    status execution_status NOT NULL,
    exit_code INTEGER NOT NULL,
    stdout_output TEXT,
    stderr_output TEXT,
    duration_ms INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 25. REVIEWER_REPORTS
CREATE TABLE reviewer_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_run_id UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    strengths JSONB NOT NULL,
    concerns JSONB NOT NULL,
    security_audit TEXT NOT NULL,
    recommendation TEXT NOT NULL, -- 'ready_to_merge', 'requires_followup'
    task_understanding TEXT NOT NULL DEFAULT '',
    implementation_summary TEXT NOT NULL DEFAULT '',
    changed_files JSONB NOT NULL DEFAULT '[]',
    requirements_coverage JSONB NOT NULL DEFAULT '[]',
    behavior_verified JSONB NOT NULL DEFAULT '[]',
    tests_summary JSONB NOT NULL DEFAULT '[]',
    test_failures JSONB NOT NULL DEFAULT '[]',
    repair_summary JSONB NOT NULL DEFAULT '[]',
    remaining_risks JSONB NOT NULL DEFAULT '[]',
    unresolved_items JSONB NOT NULL DEFAULT '[]',
    evidence JSONB NOT NULL DEFAULT '[]',
    final_status TEXT NOT NULL DEFAULT 'COMPLETED_WITH_LIMITATIONS',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 26. EXECUTION_LOGS
CREATE TABLE execution_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_run_id UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    source TEXT NOT NULL, -- 'sandbox', 'agent', 'system'
    stream TEXT NOT NULL, -- 'stdout', 'stderr', 'event'
    log_line TEXT NOT NULL,
    logged_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 27. GIT_SNAPSHOTS
CREATE TABLE git_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    commit_sha TEXT NOT NULL,
    tree_sha TEXT NOT NULL,
    parent_commit_sha TEXT,
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- INDEXES & PERFORMANCE OPTIMIZATIONS
-- =============================================================================

CREATE INDEX idx_workspaces_user ON workspaces(user_id);
CREATE INDEX idx_tasks_workspace ON tasks(workspace_id);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_agent_runs_task ON agent_runs(task_id);
CREATE INDEX idx_agent_runs_worker ON agent_runs(worker_id);
CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE INDEX idx_files_workspace_path ON files(workspace_id, relative_path);
CREATE INDEX idx_execution_logs_task ON execution_logs(task_id, logged_at);
CREATE INDEX idx_approvals_task ON approvals(task_id);
CREATE INDEX idx_staging_workspaces_task ON staging_workspaces(task_id);

-- =============================================================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- =============================================================================

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE staging_workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE code_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE diffs ENABLE ROW LEVEL SECURITY;
ALTER TABLE test_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE test_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE test_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE build_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE reviewer_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE execution_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE git_snapshots ENABLE ROW LEVEL SECURITY;

-- User isolation policies
CREATE POLICY users_select_self ON users
    FOR SELECT USING (id = auth.uid());

CREATE POLICY users_insert_self ON users
    FOR INSERT WITH CHECK (id = auth.uid());

CREATE POLICY users_update_self ON users
    FOR UPDATE USING (id = auth.uid()) WITH CHECK (id = auth.uid());

-- Credential isolation policies
CREATE POLICY credentials_owner ON credentials
    FOR ALL USING (user_id = auth.uid());

-- Workspace isolation policies
CREATE POLICY workspaces_select_owner ON workspaces
    FOR SELECT USING (user_id = auth.uid());

CREATE POLICY workspaces_insert_owner ON workspaces
    FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY workspaces_update_owner ON workspaces
    FOR UPDATE USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

CREATE POLICY workspaces_delete_owner ON workspaces
    FOR DELETE USING (user_id = auth.uid());

-- Codebase analyses isolation policy
CREATE POLICY codebase_analyses_owner ON codebase_analyses
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM workspaces
            WHERE workspaces.id = codebase_analyses.workspace_id
            AND workspaces.user_id = auth.uid()
        )
    );


-- =============================================================================
-- AUTH IDENTITY PROJECTION TRIGGER (auth.users -> public.users)
-- =============================================================================

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.users (id, email, display_name, avatar_url)
    VALUES (
        new.id,
        new.email,
        COALESCE(new.raw_user_meta_data->>'display_name', split_part(new.email, '@', 1)),
        new.raw_user_meta_data->>'avatar_url'
    )
    ON CONFLICT (id) DO UPDATE
    SET email = EXCLUDED.email,
        updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT OR UPDATE ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

ALTER TABLE loadouts ENABLE ROW LEVEL SECURITY;
ALTER TABLE files ENABLE ROW LEVEL SECURITY;
ALTER TABLE file_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE codebase_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

ALTER TABLE providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE workers ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runs ALTER COLUMN started_at DROP NOT NULL;
