"""Owner-scoped policy and progress endpoints; subprocesses live in the supervisor."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth_headers import resolve_authenticated_user_id
from ...config import get_config
from ...database import get_db
from ...recording.automation_schema import AutomationPolicy, AutomationResponse, WindowList, WindowResponse
from ...recording.automation_store import AutomationStore
from ...recording.errors import RecordingError

router = APIRouter(prefix="/recording", tags=["recording"])


async def _owner(request: Request, db: AsyncSession = Depends(get_db)) -> str:
    return await resolve_authenticated_user_id(request, db, get_config())


async def _call(operation):
    try:
        return await operation
    except RecordingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/channels/{channel_id}/automation", response_model=AutomationResponse)
async def get_automation(channel_id: str, user_id: str = Depends(_owner), db: AsyncSession = Depends(get_db)):
    return await _call(AutomationStore(db).get_policy(user_id, channel_id))


@router.put("/channels/{channel_id}/automation", response_model=AutomationResponse)
async def configure_automation(channel_id: str, policy: AutomationPolicy, user_id: str = Depends(_owner), db: AsyncSession = Depends(get_db)):
    return await _call(AutomationStore(db).put_policy(user_id, channel_id, policy))


@router.get("/channels/{channel_id}/windows", response_model=WindowList)
async def list_windows(channel_id: str, user_id: str = Depends(_owner), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db)):
    return await _call(AutomationStore(db).list_windows(user_id, channel_id, limit, offset))


@router.delete("/channels/{channel_id}/windows")
async def clear_history(channel_id: str, scope: Literal["failed", "finished"] = Query("finished"), user_id: str = Depends(_owner), db: AsyncSession = Depends(get_db)):
    return await _call(AutomationStore(db).clear_history(user_id, channel_id, scope))


@router.post("/channels/{channel_id}/windows/{window_id}/retry", response_model=WindowResponse)
async def retry_window(channel_id: str, window_id: str, user_id: str = Depends(_owner), db: AsyncSession = Depends(get_db)):
    return await _call(AutomationStore(db).retry_window(user_id, channel_id, window_id))
