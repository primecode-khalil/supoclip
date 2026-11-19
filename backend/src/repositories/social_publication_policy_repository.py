"""Short destination transactions allocate publication times, never media I/O."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import text


class SocialPublicationPolicyRepository:
    @staticmethod
    async def lock_account(db, user_id: str, account_id: str) -> bool:
        return (await db.execute(text("""
            SELECT id FROM social_accounts WHERE id=:account AND user_id=:user
              AND provider='youtube' AND revoked_at IS NULL FOR UPDATE
        """), {"user": user_id, "account": account_id})).scalar_one_or_none() is not None

    @staticmethod
    async def get(db, user_id: str, account_id: str) -> dict | None:
        row = (await db.execute(text("SELECT * FROM social_publication_policies WHERE account_id=:account AND user_id=:user"),
            {"user": user_id, "account": account_id})).mappings().first()
        return dict(row) if row else None

    @staticmethod
    async def save(db, user_id: str, account_id: str, policy: dict, *, commit: bool = True) -> None:
        await db.execute(text("""
            INSERT INTO social_publication_policies(account_id,user_id,policy,enabled_at)
            VALUES (:account,:user,CAST(:policy AS JSONB),CASE WHEN :enabled THEN NOW() ELSE NULL END)
            ON CONFLICT(account_id) DO UPDATE SET policy=EXCLUDED.policy, updated_at=NOW(),
              enabled_at=CASE WHEN :enabled AND NOT COALESCE((social_publication_policies.policy->>'enabled')::boolean,FALSE)
                              THEN NOW() ELSE social_publication_policies.enabled_at END
            WHERE social_publication_policies.user_id=EXCLUDED.user_id
        """), {"user": user_id, "account": account_id, "policy": json.dumps(policy), "enabled": bool(policy.get("enabled"))})
        if commit:
            await db.commit()

    @staticmethod
    async def next_slot(db, user_id: str, account_id: str, policy, now: datetime, *, exclude_review: str | None = None) -> datetime:
        from ..services.social_publication_policy import PUBLICATION_LEAD, next_publication_time
        tail = (await db.execute(text("""
            SELECT MAX(publish_at) FROM social_publication_slots
            WHERE user_id=:user AND account_id=:account AND cancelled_at IS NULL
              AND review_id<>COALESCE(CAST(:exclude AS VARCHAR), '')
        """), {"user": user_id, "account": account_id, "exclude": exclude_review})).scalar_one()
        after = max(now + PUBLICATION_LEAD, tail + timedelta(microseconds=1)) if tail else now + PUBLICATION_LEAD
        return next_publication_time(policy.schedule, policy.timezone, after)

    @staticmethod
    async def reserve(db, review_id: str, now: datetime, *, custom_local: str | None = None,
                      move_if_late: bool = False, commit: bool = True) -> datetime:
        from ..services.social_publication_policy import PublishingPolicy, PUBLICATION_LEAD, local_publication_time
        review = (await db.execute(text("SELECT user_id,account_id FROM social_review_items WHERE id=:id"), {"id": review_id})).mappings().first()
        if not review or not await SocialPublicationPolicyRepository.lock_account(db, review["user_id"], review["account_id"]):
            raise ValueError("Review destination is unavailable")
        row = await SocialPublicationPolicyRepository.get(db, review["user_id"], review["account_id"])
        policy = PublishingPolicy.model_validate(row["policy"] if row else {})
        existing = (await db.execute(text("SELECT publish_at FROM social_publication_slots WHERE review_id=:id AND cancelled_at IS NULL"), {"id": review_id})).scalar_one_or_none()
        if existing and not custom_local and (not move_if_late or existing >= now + PUBLICATION_LEAD):
            if commit:
                await db.commit()
            return existing
        if custom_local:
            slot = local_publication_time(custom_local, policy.timezone, now + PUBLICATION_LEAD)
            occupied = (await db.execute(text("SELECT review_id FROM social_publication_slots WHERE account_id=:account AND publish_at=:slot AND cancelled_at IS NULL AND review_id<>:id"),
                {"account": review["account_id"], "slot": slot, "id": review_id})).scalar_one_or_none()
            if occupied:
                raise ValueError("Another approved clip already has that publication time")
        else:
            slot = await SocialPublicationPolicyRepository.next_slot(db, review["user_id"], review["account_id"], policy, now, exclude_review=review_id)
        await db.execute(text("""
            INSERT INTO social_publication_slots(review_id,user_id,account_id,publish_at)
            SELECT r.id,r.user_id,r.account_id,:slot FROM social_review_items r WHERE r.id=:id
            ON CONFLICT(review_id) DO UPDATE SET publish_at=EXCLUDED.publish_at,cancelled_at=NULL
        """), {"id": review_id, "slot": slot})
        if commit:
            await db.commit()
        return slot
