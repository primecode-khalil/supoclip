ALTER TABLE youtube_uploads ADD COLUMN IF NOT EXISTS desired_publish_at TIMESTAMPTZ;
ALTER TABLE youtube_uploads ADD COLUMN IF NOT EXISTS confirmed_publish_at TIMESTAMPTZ;
ALTER TABLE youtube_uploads ADD COLUMN IF NOT EXISTS schedule_requested_at TIMESTAMPTZ;
