-- Add application statuses absent from the initial schema. Commit this migration
-- before writing rows that use the new enum values.
ALTER TYPE task_status ADD VALUE IF NOT EXISTS 'repairing';
ALTER TYPE execution_status ADD VALUE IF NOT EXISTS 'success';
ALTER TYPE execution_status ADD VALUE IF NOT EXISTS 'retryable_error';
ALTER TYPE execution_status ADD VALUE IF NOT EXISTS 'blocked';
ALTER TYPE execution_status ADD VALUE IF NOT EXISTS 'rate_limited';
ALTER TYPE execution_status ADD VALUE IF NOT EXISTS 'not_applicable';

-- These tenant-bearing tables previously had no RLS enforcement. Backend
-- repositories use the trusted database role; browser access is denied unless
-- an explicit owner policy exists.
ALTER TABLE loadouts ENABLE ROW LEVEL SECURITY;
ALTER TABLE files ENABLE ROW LEVEL SECURITY;
ALTER TABLE file_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE codebase_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

-- SECURITY DEFINER functions must not inherit a caller-controlled search path.
ALTER FUNCTION public.handle_new_user() SET search_path = public;

ALTER TABLE providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE workers ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runs ALTER COLUMN started_at DROP NOT NULL;
