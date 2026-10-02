CREATE TABLE IF NOT EXISTS rlb_devices (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rlb_devices_user_idx ON rlb_devices(user_id);
ALTER TABLE rlb_devices ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rlb_devices FROM PUBLIC, anon, authenticated;
GRANT ALL ON rlb_devices TO service_role;

CREATE TABLE IF NOT EXISTS rlb_device_pairings (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    used_at timestamptz
);
ALTER TABLE rlb_device_pairings ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rlb_device_pairings FROM PUBLIC, anon, authenticated;
GRANT ALL ON rlb_device_pairings TO service_role;

CREATE TABLE IF NOT EXISTS rlb_remote_commands (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    device_id uuid NOT NULL REFERENCES rlb_devices(id) ON DELETE CASCADE,
    idempotency_key text NOT NULL,
    status text NOT NULL CHECK (status IN ('QUEUED','DELIVERED','ACKNOWLEDGED','EXECUTING','SUCCEEDED','FAILED','EXPIRED')),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(device_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS rlb_commands_pending_idx
    ON rlb_remote_commands(device_id, status, created_at);
ALTER TABLE rlb_remote_commands ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rlb_remote_commands FROM PUBLIC, anon, authenticated;
GRANT ALL ON rlb_remote_commands TO service_role;

CREATE TABLE IF NOT EXISTS rlb_device_events (
    device_id uuid NOT NULL REFERENCES rlb_devices(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    event_id uuid NOT NULL,
    task_id uuid NOT NULL,
    sequence bigint NOT NULL CHECK (sequence > 0),
    event_type text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    source text NOT NULL,
    PRIMARY KEY (device_id,event_id)
);
CREATE INDEX IF NOT EXISTS rlb_device_events_cursor_idx
    ON rlb_device_events(device_id,task_id,sequence);
CREATE UNIQUE INDEX IF NOT EXISTS rlb_device_events_sequence_uq
    ON rlb_device_events(device_id,task_id,sequence);
CREATE INDEX IF NOT EXISTS rlb_device_events_recent_idx
    ON rlb_device_events(device_id,created_at DESC);
ALTER TABLE rlb_device_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rlb_device_events FROM PUBLIC, anon, authenticated;
GRANT ALL ON rlb_device_events TO service_role;

CREATE TABLE IF NOT EXISTS rlb_schema_versions(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE rlb_schema_versions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON rlb_schema_versions FROM PUBLIC, anon, authenticated;
GRANT ALL ON rlb_schema_versions TO service_role;
INSERT INTO rlb_schema_versions(version) VALUES (6) ON CONFLICT DO NOTHING;
