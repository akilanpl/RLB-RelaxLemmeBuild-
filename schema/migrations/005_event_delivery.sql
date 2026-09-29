-- Durable command lifecycle and commit-ordered per-task event cursors.
BEGIN;
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
    -- Per-task row locking makes sequence order agree with commit order. Without
    -- this, a poll cursor can skip a lower sequence still in another transaction.
    PERFORM 1 FROM tasks WHERE id=tid FOR UPDATE;
    kind := CASE TG_TABLE_NAME
        WHEN 'plans' THEN 'plan.generated'
        WHEN 'staging_workspaces' THEN 'staging.created'
        WHEN 'code_proposals' THEN 'code.' || COALESCE(doc->>'status','created')
        WHEN 'approvals' THEN (doc->>'gate_type') || '.' || (doc->>'status')
        WHEN 'agent_runs' THEN 'agent.' || (doc->>'execution_status')
        WHEN 'test_plans' THEN 'test_plan.generated'
        WHEN 'test_executions' THEN CASE WHEN TG_OP='INSERT' THEN 'tests.started'
            WHEN TG_OP='UPDATE' AND doc->'command_results' IS DISTINCT FROM to_jsonb(OLD)->'command_results' THEN
                'command.' || coalesce(doc->'command_results'-> (-1)->>'status','updated')
            WHEN (doc->>'all_passed')::boolean THEN 'tests.passed' ELSE 'tests.updated' END
        WHEN 'build_results' THEN 'test.log'
        WHEN 'reviewer_reports' THEN 'review.completed'
        WHEN 'git_snapshots' THEN 'promotion.completed'
        ELSE TG_TABLE_NAME || '.updated' END;
    INSERT INTO task_events(task_id,workspace_id,event_type,actor_type,actor_id,payload)
    VALUES(tid,wid,kind,CASE WHEN TG_TABLE_NAME='approvals' THEN 'user' ELSE 'system' END,
        (doc->>'reviewed_by')::uuid,
        jsonb_build_object('entity_id',doc->>'id','operation',TG_OP,
            'command_id',doc->'command_results'-> (-1)->>'command_id',
            'sandbox_id',doc->'command_results'-> (-1)->>'sandbox_id'));
    RETURN NEW;
END;
$$;
CREATE TABLE IF NOT EXISTS rlb_schema_versions(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE rlb_schema_versions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rlb_schema_versions FROM PUBLIC,anon,authenticated;
GRANT ALL ON rlb_schema_versions TO service_role;
INSERT INTO rlb_schema_versions(version) VALUES (5) ON CONFLICT DO NOTHING;
COMMIT;
