ALTER TABLE social_posts ADD COLUMN IF NOT EXISTS provider_options JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS social_publication_policies (
    account_id VARCHAR(36) PRIMARY KEY REFERENCES social_accounts(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS social_review_items (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id VARCHAR(36) NOT NULL REFERENCES social_accounts(id) ON DELETE CASCADE,
    task_id VARCHAR(36) REFERENCES tasks(id) ON DELETE SET NULL,
    clip_id VARCHAR(36) REFERENCES generated_clips(id) ON DELETE SET NULL,
    source_key TEXT,
    render_version TEXT NOT NULL,
    source_file_path TEXT NOT NULL,
    media_sha256 TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','cancelled')),
    post_id VARCHAR(36) REFERENCES social_posts(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at TIMESTAMPTZ,
    UNIQUE(user_id, account_id, clip_id)
);
CREATE INDEX IF NOT EXISTS social_review_pending ON social_review_items(user_id,account_id,status,created_at);

CREATE TABLE IF NOT EXISTS social_publication_slots (
    review_id VARCHAR(36) PRIMARY KEY REFERENCES social_review_items(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id VARCHAR(36) NOT NULL REFERENCES social_accounts(id) ON DELETE CASCADE,
    publish_at TIMESTAMPTZ NOT NULL,
    cancelled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS social_publication_slot_time ON social_publication_slots(account_id,publish_at) WHERE cancelled_at IS NULL;

CREATE TABLE IF NOT EXISTS social_provider_limits (
    provider TEXT NOT NULL,
    project_key TEXT NOT NULL,
    bucket TEXT NOT NULL,
    retry_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(provider,project_key,bucket)
);
