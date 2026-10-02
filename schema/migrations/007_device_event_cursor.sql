ALTER TABLE rlb_device_events
    ADD COLUMN IF NOT EXISTS cursor bigint GENERATED ALWAYS AS IDENTITY;

CREATE UNIQUE INDEX IF NOT EXISTS rlb_device_events_device_cursor_uq
    ON rlb_device_events(device_id, cursor);

INSERT INTO rlb_schema_versions(version) VALUES (7) ON CONFLICT DO NOTHING;
