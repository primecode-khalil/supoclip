-- Public keys and short-lived, hashed pairing tokens only. Device secrets stay on the Mac.
CREATE TABLE IF NOT EXISTS home_proxy_devices (
    id TEXT PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    public_key TEXT NOT NULL,
    paired_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_home_proxy_one_active_device
    ON home_proxy_devices ((TRUE)) WHERE revoked_at IS NULL;
CREATE TABLE IF NOT EXISTS home_proxy_pairings (
    token_hash VARCHAR(64) PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    CONSTRAINT ck_home_proxy_token_hash CHECK (token_hash ~ '^[0-9a-f]{64}$')
);
CREATE TABLE IF NOT EXISTS home_proxy_pair_attempts (
    peer_hash VARCHAR(64) PRIMARY KEY,
    window_started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    attempts INTEGER NOT NULL,
    CONSTRAINT ck_home_proxy_peer_hash CHECK (peer_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_home_proxy_attempts CHECK (attempts BETWEEN 1 AND 11)
);
