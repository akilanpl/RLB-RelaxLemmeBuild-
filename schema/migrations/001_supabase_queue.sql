-- Supabase Queue is a pgmq basic (logged/durable) queue, used server-side only.
CREATE EXTENSION IF NOT EXISTS pgmq;
SELECT pgmq.create('task_execution');
CREATE OR REPLACE FUNCTION public.enqueue_task_job() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF NEW.status::text IN ('ready', 'planning', 'coding', 'test_planning', 'test_executing', 'repairing', 'reviewing') THEN
        PERFORM pgmq.send('task_execution', jsonb_build_object(
            'task_id', NEW.id, 'task_version', NEW.version, 'requested_at', NOW()));
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS task_job_enqueue ON tasks;
CREATE TRIGGER task_job_enqueue AFTER INSERT OR UPDATE OF status ON tasks
    FOR EACH ROW EXECUTE FUNCTION public.enqueue_task_job();
-- No browser access to pgmq is required. Use a backend-only database connection.
