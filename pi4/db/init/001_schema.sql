CREATE TABLE IF NOT EXISTS mqtt_message (
    id BIGSERIAL PRIMARY KEY,
    topic TEXT NOT NULL,
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS mqtt_message_received_at_idx
    ON mqtt_message (received_at DESC);

CREATE TABLE IF NOT EXISTS vision_event (
    event_id TEXT PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    camera_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    confidence REAL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS vision_event_occurred_at_idx
    ON vision_event (occurred_at DESC);

CREATE TABLE IF NOT EXISTS vision_status (
    camera_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS safety_state (
    state_key TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
