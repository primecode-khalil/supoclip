-- Recording bookkeeping only. No capture process or media paths are registered here.
CREATE TABLE IF NOT EXISTS recording_channels (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform VARCHAR(20) NOT NULL,
    handle VARCHAR(255) NOT NULL,
    url VARCHAR(500) NOT NULL,
    name VARCHAR(120) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    quality VARCHAR(255) NOT NULL DEFAULT 'best',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_recording_channel_platform CHECK (platform IN ('twitch', 'kick', 'youtube'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_recording_channel_identity ON recording_channels (user_id, platform, handle);

CREATE TABLE IF NOT EXISTS recording_sessions (
    id VARCHAR(36) PRIMARY KEY,
    channel_id VARCHAR(36) NOT NULL REFERENCES recording_channels(id) ON DELETE CASCADE,
    external_id VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'created',
    settings_snapshot JSONB NOT NULL,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_recording_session_status CHECK (status IN ('created', 'recording', 'interrupted', 'completed', 'failed', 'cancelled')),
    CONSTRAINT ck_recording_session_terminal_time CHECK ((status IN ('completed', 'failed', 'cancelled')) = (ended_at IS NOT NULL)),
    CONSTRAINT ck_recording_session_started_time CHECK (status NOT IN ('recording', 'interrupted', 'completed') OR started_at IS NOT NULL),
    CONSTRAINT ck_recording_session_created_time CHECK (status <> 'created' OR started_at IS NULL),
    CONSTRAINT ck_recording_session_started_order CHECK (started_at IS NULL OR started_at >= created_at),
    CONSTRAINT ck_recording_session_ended_order CHECK (ended_at IS NULL OR ended_at >= COALESCE(started_at, created_at))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_recording_session_external_id ON recording_sessions (channel_id, external_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_recording_session_active ON recording_sessions (channel_id) WHERE status IN ('created', 'recording', 'interrupted');
CREATE INDEX IF NOT EXISTS ix_recording_sessions_channel_created ON recording_sessions (channel_id, created_at, id);
