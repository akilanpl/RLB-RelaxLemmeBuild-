-- Additive; apply once per environment after 001 and 002.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS ai_call_count integer NOT NULL DEFAULT 0 CHECK (ai_call_count >= 0);
CREATE TABLE IF NOT EXISTS provider_calls (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    evidence jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS provider_calls_task_time ON provider_calls(task_id, created_at);
ALTER TABLE provider_calls ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS provider_calls_owner_read ON provider_calls;
CREATE POLICY provider_calls_owner_read ON provider_calls FOR SELECT TO authenticated
USING (EXISTS (SELECT 1 FROM tasks t JOIN workspaces w ON w.id=t.workspace_id
              WHERE t.id=provider_calls.task_id AND w.user_id=auth.uid()));
REVOKE ALL ON provider_calls FROM anon;
REVOKE INSERT, UPDATE, DELETE ON provider_calls FROM authenticated;
CREATE INDEX IF NOT EXISTS tasks_user_created ON tasks(user_id, created_at DESC);
-- Queue operations are trusted server operations only.
REVOKE ALL ON SCHEMA pgmq FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA pgmq FROM anon, authenticated;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA pgmq FROM PUBLIC, anon, authenticated;
-- The browser reads through RLS but cannot forge workflow state or approvals.
REVOKE INSERT, UPDATE, DELETE ON tasks, agent_runs, agent_states, approvals, plans,
    code_proposals, diffs, staging_workspaces, test_plans, test_cases, test_executions,
    build_results, reviewer_reports, execution_logs, git_snapshots, files,
    file_metadata, workspaces, workspace_settings, conversations, messages,
    codebase_analyses, workers, providers, loadouts FROM anon, authenticated;
REVOKE ALL ON credentials FROM anon, authenticated;

ALTER TABLE test_executions ADD COLUMN IF NOT EXISTS command_results jsonb NOT NULL DEFAULT '[]'::jsonb;
CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id text PRIMARY KEY,
    seen_at timestamptz NOT NULL
);
ALTER TABLE worker_heartbeats ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON worker_heartbeats FROM anon, authenticated;

CREATE TABLE IF NOT EXISTS task_events (
    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    event_type text NOT NULL,
    actor_type text NOT NULL DEFAULT 'system',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS task_events_task_sequence ON task_events(task_id, sequence);
ALTER TABLE task_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS task_events_owner_read ON task_events;
CREATE POLICY task_events_owner_read ON task_events FOR SELECT TO authenticated
USING (EXISTS (SELECT 1 FROM workspaces w WHERE w.id=task_events.workspace_id AND w.user_id=auth.uid()));
REVOKE ALL ON task_events FROM anon;
REVOKE INSERT, UPDATE, DELETE ON task_events FROM authenticated;
CREATE OR REPLACE FUNCTION public.record_task_state_event() RETURNS trigger
LANGUAGE plpgsql SET search_path=public AS $$
BEGIN
    INSERT INTO task_events(task_id, workspace_id, event_type, payload)
    VALUES (NEW.id, NEW.workspace_id,
        CASE WHEN TG_OP='INSERT' THEN 'task.created' ELSE 'task.' || NEW.status::text END,
        jsonb_build_object('version', NEW.version, 'status', NEW.status));
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS task_state_event ON tasks;
CREATE TRIGGER task_state_event AFTER INSERT OR UPDATE OF status ON tasks
FOR EACH ROW EXECUTE FUNCTION public.record_task_state_event();
-- Supplement state events with durable entity evidence. Payloads contain IDs/status only.
ALTER TABLE task_events ADD COLUMN IF NOT EXISTS actor_id uuid;
CREATE OR REPLACE FUNCTION public.record_task_entity_event() RETURNS trigger
LANGUAGE plpgsql SET search_path=public AS $$
DECLARE doc jsonb := to_jsonb(NEW); tid uuid; wid uuid; kind text;
BEGIN
    tid := (doc->>'task_id')::uuid;
    IF TG_TABLE_NAME='build_results' THEN
        SELECT task_id INTO tid FROM test_executions WHERE id=(doc->>'test_execution_id')::uuid;
    END IF;
    IF tid IS NULL THEN RETURN NEW; END IF;
    SELECT workspace_id INTO wid FROM tasks WHERE id=tid;
    IF wid IS NULL THEN RETURN NEW; END IF;
    kind := CASE TG_TABLE_NAME
        WHEN 'plans' THEN 'plan.generated'
        WHEN 'staging_workspaces' THEN 'staging.created'
        WHEN 'code_proposals' THEN 'code.' || COALESCE(doc->>'status','created')
        WHEN 'approvals' THEN (doc->>'gate_type') || '.' || (doc->>'status')
        WHEN 'agent_runs' THEN 'agent.' || (doc->>'execution_status')
        WHEN 'test_plans' THEN 'test_plan.generated'
        WHEN 'test_executions' THEN CASE WHEN TG_OP='INSERT' THEN 'tests.started'
            WHEN (doc->>'all_passed')::boolean THEN 'tests.passed' ELSE 'tests.updated' END
        WHEN 'build_results' THEN 'test.log'
        WHEN 'reviewer_reports' THEN 'review.completed'
        WHEN 'git_snapshots' THEN 'promotion.completed'
        ELSE TG_TABLE_NAME || '.updated' END;
    INSERT INTO task_events(task_id,workspace_id,event_type,actor_type,actor_id,payload)
    VALUES(tid,wid,kind,CASE WHEN TG_TABLE_NAME='approvals' THEN 'user' ELSE 'system' END,
        (doc->>'reviewed_by')::uuid,
        jsonb_build_object('entity_id',doc->>'id','operation',TG_OP));
    RETURN NEW;
END;
$$;
DO $$ DECLARE tbl text; BEGIN
    FOREACH tbl IN ARRAY ARRAY['plans','staging_workspaces','code_proposals','approvals','agent_runs',
        'test_plans','test_executions','build_results','reviewer_reports','git_snapshots'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS rlb_entity_event ON %I', tbl);
        EXECUTE format('CREATE TRIGGER rlb_entity_event AFTER INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION public.record_task_entity_event()', tbl);
    END LOOP;
END $$;

-- Also lock down optional Supabase HTTP queue wrappers when installed.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname='pgmq_public') THEN
        REVOKE ALL ON SCHEMA pgmq_public FROM PUBLIC, anon, authenticated;
        REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA pgmq_public FROM PUBLIC, anon, authenticated;
    END IF;
END $$;
CREATE OR REPLACE FUNCTION public.enqueue_task_job() RETURNS trigger
LANGUAGE plpgsql SET search_path=public AS $$
BEGIN
    IF NEW.status::text IN ('ready','analyzing','planning','staging_setup','promoting','coding','test_planning','test_executing','repairing','reviewing') THEN
        PERFORM pgmq.send('task_execution', jsonb_build_object('task_id',NEW.id,'task_version',NEW.version,'requested_at',now()));
    END IF;
    RETURN NEW;
END;
$$;
ALTER TABLE test_executions ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'unavailable';
UPDATE test_executions SET status=CASE WHEN all_passed THEN 'success'
    WHEN failure_report IS NOT NULL THEN 'failed' ELSE 'unavailable' END WHERE status='unavailable';

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS approved_proposal_id uuid REFERENCES code_proposals(id);
