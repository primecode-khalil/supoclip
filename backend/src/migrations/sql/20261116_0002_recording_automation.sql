-- Policy is opt-in. Leases persist fencing generations across process restarts.
CREATE TABLE IF NOT EXISTS recording_automation (
    channel_id VARCHAR(36) PRIMARY KEY REFERENCES recording_channels(id) ON DELETE CASCADE,
    policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS recording_automation_leases (
    channel_id VARCHAR(36) PRIMARY KEY REFERENCES recording_channels(id) ON DELETE CASCADE,
    holder VARCHAR(255) NOT NULL,
    fence BIGINT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    last_heartbeat_at TIMESTAMPTZ NOT NULL,
    last_error TEXT,
    CONSTRAINT ck_recording_lease_fence CHECK (fence > 0)
);
CREATE TABLE IF NOT EXISTS recording_windows (
    id VARCHAR(36) PRIMARY KEY,
    channel_id VARCHAR(36) NOT NULL REFERENCES recording_channels(id) ON DELETE CASCADE,
    session_id VARCHAR(36) NOT NULL REFERENCES recording_sessions(id) ON DELETE CASCADE,
    epoch VARCHAR(80) NOT NULL,
    sequence INTEGER NOT NULL,
    source_path VARCHAR(1024) NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL,
    start_seconds DOUBLE PRECISION NOT NULL,
    end_seconds DOUBLE PRECISION NOT NULL,
    overlap_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    task_id VARCHAR(36) REFERENCES tasks(id) ON DELETE SET NULL,
    upload_ref VARCHAR(1024),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ,
    last_error TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_recording_window_status CHECK (status IN ('pending', 'submitting', 'processing', 'publishing', 'completed', 'blocked')),
    CONSTRAINT ck_recording_window_counts CHECK (sequence >= 0 AND size_bytes > 0 AND attempts >= 0),
    CONSTRAINT ck_recording_window_range CHECK (start_seconds >= 0 AND end_seconds > start_seconds AND end_seconds < 'Infinity'::double precision AND overlap_seconds >= 0 AND overlap_seconds < end_seconds - start_seconds),
    CONSTRAINT ck_recording_window_hash CHECK (sha256 ~ '^[0-9a-f]{64}$')
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_recording_window_identity ON recording_windows (channel_id, session_id, epoch, sequence);
CREATE INDEX IF NOT EXISTS ix_recording_windows_pending ON recording_windows (channel_id, status, next_attempt_at, created_at);
