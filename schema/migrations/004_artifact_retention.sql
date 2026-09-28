-- Server-owned cleanup ledger. Keep tombstones permanently to fence late publication.
BEGIN;
ALTER TABLE git_snapshots ADD COLUMN IF NOT EXISTS artifact_root_path TEXT;
CREATE TABLE IF NOT EXISTS artifact_cleanup (
    root_path TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at TIMESTAMPTZ,
    deleted_objects BIGINT NOT NULL DEFAULT 0,
    last_error TEXT,
    completed_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS artifact_retention_scans (
    root_path TEXT PRIMARY KEY, checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE artifact_retention_scans ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON artifact_retention_scans FROM PUBLIC, anon, authenticated;
GRANT ALL ON artifact_retention_scans TO service_role;
ALTER TABLE artifact_cleanup ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON artifact_cleanup FROM PUBLIC, anon, authenticated;
GRANT ALL ON artifact_cleanup TO service_role;

CREATE OR REPLACE FUNCTION guard_retired_artifact() RETURNS trigger
LANGUAGE plpgsql SET search_path = public AS $$
DECLARE root TEXT;
BEGIN
    root := to_jsonb(NEW)->>TG_ARGV[0];
    IF EXISTS (SELECT 1 FROM artifact_cleanup WHERE root_path = root) THEN
        RAISE EXCEPTION 'Artifact has been retired';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS guard_retired_canonical ON workspaces;
CREATE TRIGGER guard_retired_canonical BEFORE INSERT OR UPDATE OF canonical_root_path
ON workspaces FOR EACH ROW EXECUTE FUNCTION guard_retired_artifact('canonical_root_path');
DROP TRIGGER IF EXISTS guard_retired_staging ON staging_workspaces;
CREATE TRIGGER guard_retired_staging BEFORE INSERT OR UPDATE OF staging_root_path
ON staging_workspaces FOR EACH ROW EXECUTE FUNCTION guard_retired_artifact('staging_root_path');
DROP TRIGGER IF EXISTS guard_retired_snapshot ON git_snapshots;
CREATE TRIGGER guard_retired_snapshot BEFORE INSERT OR UPDATE OF artifact_root_path
ON git_snapshots FOR EACH ROW EXECUTE FUNCTION guard_retired_artifact('artifact_root_path');
-- Preserve every published tree, including imported roots and superseded canonical trees.
CREATE TABLE IF NOT EXISTS artifact_audit_roots (
    root_path TEXT PRIMARY KEY, workspace_id UUID NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE artifact_audit_roots ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON artifact_audit_roots FROM PUBLIC, anon, authenticated;
GRANT ALL ON artifact_audit_roots TO service_role;
INSERT INTO artifact_audit_roots(root_path,workspace_id)
SELECT canonical_root_path,id FROM workspaces ON CONFLICT DO NOTHING;
CREATE OR REPLACE FUNCTION retain_published_artifact() RETURNS trigger
LANGUAGE plpgsql SET search_path=public AS $$
BEGIN
    INSERT INTO artifact_audit_roots(root_path,workspace_id)
    VALUES (NEW.canonical_root_path,NEW.id) ON CONFLICT DO NOTHING;
    IF TG_OP='UPDATE' THEN
        INSERT INTO artifact_audit_roots(root_path,workspace_id)
        VALUES (OLD.canonical_root_path,OLD.id) ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS retain_published_artifact ON workspaces;
CREATE TRIGGER retain_published_artifact AFTER INSERT OR UPDATE OF canonical_root_path
ON workspaces FOR EACH ROW EXECUTE FUNCTION retain_published_artifact();

-- Count actual fenced executions, not pgmq reads that only encountered a busy lock.
CREATE TABLE IF NOT EXISTS queue_delivery_attempts (
    queue_name TEXT NOT NULL, receipt BIGINT NOT NULL, attempts INTEGER NOT NULL,
    PRIMARY KEY(queue_name,receipt)
);
ALTER TABLE queue_delivery_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON queue_delivery_attempts FROM PUBLIC, anon, authenticated;
GRANT ALL ON queue_delivery_attempts TO service_role;
COMMIT;
