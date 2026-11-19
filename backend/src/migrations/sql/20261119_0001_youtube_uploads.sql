CREATE TABLE IF NOT EXISTS youtube_uploads (
    post_id VARCHAR(36) PRIMARY KEY REFERENCES social_posts(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    media_sha256 TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    metadata_snapshot JSONB NOT NULL,
    session_url_encrypted TEXT,
    confirmed_bytes BIGINT NOT NULL DEFAULT 0 CHECK (confirmed_bytes >= 0),
    bytes_started BOOLEAN NOT NULL DEFAULT FALSE,
    video_id TEXT,
    stage TEXT NOT NULL DEFAULT 'queued',
    reason_code TEXT,
    actual_visibility TEXT,
    next_attempt_at TIMESTAMPTZ DEFAULT NOW(),
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    processing_started_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (confirmed_bytes <= size_bytes)
);
CREATE INDEX IF NOT EXISTS youtube_uploads_due ON youtube_uploads(next_attempt_at)
    WHERE stage NOT IN ('ready', 'needs_attention');
