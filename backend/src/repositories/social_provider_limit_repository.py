"""Quota waits are shared by project and API bucket, without exposing project IDs."""
import hashlib
from datetime import datetime, timedelta, timezone
from sqlalchemy import text


class SocialProviderLimitRepository:
    @staticmethod
    def project(config):
        return hashlib.sha256((config.youtube_oauth_client_id or "unconfigured").encode()).hexdigest()

    @staticmethod
    async def due(db, config, bucket):
        value = (await db.execute(text("SELECT retry_at FROM social_provider_limits WHERE provider='youtube' AND project_key=:project AND bucket=:bucket AND retry_at>NOW()"),
            {"project":SocialProviderLimitRepository.project(config),"bucket":bucket})).scalar_one_or_none()
        await db.commit()
        return value

    @staticmethod
    async def defer(db, config, bucket):
        until = datetime.now(timezone.utc)+timedelta(hours=1)
        await db.execute(text("""
            INSERT INTO social_provider_limits(provider,project_key,bucket,retry_at) VALUES('youtube',:project,:bucket,:at)
            ON CONFLICT(provider,project_key,bucket) DO UPDATE SET retry_at=GREATEST(social_provider_limits.retry_at,EXCLUDED.retry_at)
        """), {"project":SocialProviderLimitRepository.project(config),"bucket":bucket,"at":until})
        await db.commit()
