"""Preview and acknowledge the remote uploads attached to library deletion."""
from pydantic import BaseModel, ConfigDict, Field
from ..repositories.social_repository import SocialRepository


class SourceDeletionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_ids: list[str] = Field(min_length=1, max_length=1000)
    clip_id: str | None = Field(default=None, max_length=36)


class SourceDeletionConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delete_social_post_ids: list[str] = Field(default_factory=list,max_length=1000)


async def require_social_deletion_ack(db, user_id, task_id, *, clip_id=None, confirmed=False, selected_post_ids=None):
    from fastapi import HTTPException
    impact = await SocialRepository.deletion_impact(db,user_id,[task_id],clip_id=clip_id)
    if (impact["affected"] or selected_post_ids) and not confirmed:
        raise HTTPException(status_code=409, detail={"message":"Deleting this library source also permanently deletes its linked pending YouTube uploads. Review the affected uploads and confirm deletion.",
            "social_deletion_required":True, **impact})

    from sqlalchemy import text
    selected = list(selected_post_ids or [])
    owned = list((await db.execute(text("""
        SELECT id FROM social_posts WHERE user_id=:user AND task_id=:task
          AND (CAST(:clip AS VARCHAR) IS NULL OR clip_id=:clip)
          AND id=ANY(CAST(:ids AS VARCHAR[])) AND provider_options @> '{"native_schedule": true}'
    """), {"user":user_id,"task":task_id,"clip":clip_id,"ids":selected})).scalars()) if selected else []
    fresh = [p["id"] for p in impact["affected"]]
    if selected_post_ids is not None and set(fresh)-set(owned):
        raise HTTPException(status_code=409, detail={"message":"The linked uploads changed. Reload the deletion warning and confirm the updated list.","social_deletion_required":True,**impact})
    return list(dict.fromkeys(fresh+owned))
