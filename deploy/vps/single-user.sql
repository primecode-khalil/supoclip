-- Optional, private single-operator installation only. Not a global migration.
-- Install after backend initialization, before starting the frontend.
BEGIN;
LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE;
DO $$
BEGIN
    IF (SELECT count(*) FROM users) > 1 THEN
        RAISE EXCEPTION 'Single-operator setup cannot be enabled on an installation with multiple owners';
    END IF;
END
$$;
CREATE TABLE IF NOT EXISTS single_user_installation (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    claimed BOOLEAN NOT NULL DEFAULT FALSE
);
INSERT INTO single_user_installation (singleton, claimed)
VALUES (TRUE, EXISTS (SELECT 1 FROM users))
ON CONFLICT (singleton) DO UPDATE
SET claimed = single_user_installation.claimed OR EXCLUDED.claimed;
CREATE OR REPLACE FUNCTION enforce_single_user_installation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE already_claimed BOOLEAN;
BEGIN
    -- Serialize concurrent first signups across all frontend replicas.
    PERFORM pg_advisory_xact_lock(731314, 1);
    SELECT claimed INTO already_claimed FROM single_user_installation
    WHERE singleton = TRUE FOR UPDATE;
    IF already_claimed OR EXISTS (SELECT 1 FROM users) THEN
        RAISE EXCEPTION 'Registration is unavailable for this installation';
    END IF;
    UPDATE single_user_installation SET claimed = TRUE WHERE singleton = TRUE;
    NEW.is_admin := TRUE;
    RETURN NEW;
END
$$;
DROP TRIGGER IF EXISTS single_user_installation_guard ON users;
CREATE TRIGGER single_user_installation_guard
BEFORE INSERT ON users FOR EACH ROW EXECUTE FUNCTION enforce_single_user_installation();
-- A one-owner preexisting installation has the same operator role.
UPDATE users SET is_admin = TRUE;
COMMIT;
