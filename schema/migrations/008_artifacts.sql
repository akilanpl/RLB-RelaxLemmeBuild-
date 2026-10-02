-- Task-linked uploads use the existing private workspace-artifacts bucket.
-- Local device task/workspace IDs are associated by the paired-device event
-- stream; they are intentionally not foreign keys to hosted task/workspace rows.
-- Preserve metadata tombstones through account/device removal so expired object
-- cleanup can still find and delete the private Storage objects.
BEGIN;

CREATE TABLE IF NOT EXISTS rlb_task_artifacts (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL,
    device_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    task_id uuid NOT NULL,
    name text NOT NULL CHECK (
        length(name) BETWEEN 1 AND 120
        AND name ~ '^[A-Za-z0-9][A-Za-z0-9._ -]*$'
        AND name !~ '[. ]$'
    ),
    content_type text NOT NULL DEFAULT 'application/octet-stream',
    object_path text NOT NULL UNIQUE,
    size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 26214400),
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    deleted_at timestamptz,
    cleanup_completed_at timestamptz,
    CHECK (expires_at > created_at)
);
CREATE INDEX IF NOT EXISTS rlb_task_artifacts_user_task_idx
    ON rlb_task_artifacts(user_id,task_id,created_at DESC);
CREATE INDEX IF NOT EXISTS rlb_task_artifacts_expiry_idx
    ON rlb_task_artifacts(expires_at) WHERE cleanup_completed_at IS NULL;

ALTER TABLE rlb_task_artifacts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rlb_task_artifacts FROM PUBLIC, anon, authenticated;
GRANT ALL ON rlb_task_artifacts TO service_role;

INSERT INTO rlb_schema_versions(version) VALUES (8) ON CONFLICT DO NOTHING;
COMMIT;
