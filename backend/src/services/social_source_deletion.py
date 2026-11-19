"""Preview and acknowledge the remote uploads attached to library deletion."""
from pydantic import BaseModel, ConfigDict, Field
from ..repositories.social_repository import SocialRepository


class SourceDeletionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_ids: list[str] = Field(min_length=1, max_length=1000)
    clip_id: str | None = Field(default=None, max_length=36)


async def require_social_deletion_ack(db, user_id, task_id, *, clip_id=None, confirmed=False):
    from fastapi import HTTPException
    impact = await SocialRepository.deletion_impact(db,user_id,[task_id],clip_id=clip_id)
    if impact["affected"] and not confirmed:
        raise HTTPException(status_code=409, detail={"message":"Deleting this library source also permanently deletes its linked pending YouTube uploads. Review the affected uploads and confirm deletion.",
            "social_deletion_required":True, **impact})
