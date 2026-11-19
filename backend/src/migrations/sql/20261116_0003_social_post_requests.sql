-- The post and request receipt are inserted in one transaction. External upload
-- reconciliation remains the responsibility of the existing social worker.
CREATE TABLE IF NOT EXISTS social_post_requests (
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_key VARCHAR(200) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    post_id VARCHAR(36) REFERENCES social_posts(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, request_key)
);
