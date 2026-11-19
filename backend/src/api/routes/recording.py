"""Authenticated recording bookkeeping API; no process start/stop endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth_headers import resolve_authenticated_user_id
from ...config import get_config
from ...database import get_db
from ...recording.errors import RecordingError
from ...recording.schemas import (
    ChannelCreate,
    ChannelList,
    ChannelResponse,
    ChannelUpdate,
    SessionCreate,
    SessionList,
    SessionResponse,
    SessionUpdate,
)
from ...services.recording_service import RecordingService

router = APIRouter(prefix="/recording", tags=["recording"])


async def _owner(request: Request, db: AsyncSession = Depends(get_db)) -> str:
    return await resolve_authenticated_user_id(request, db, get_config())


async def _call(operation):
    try:
        return await operation
    except RecordingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/channels", response_model=ChannelResponse, status_code=201)
async def create_channel(
    payload: ChannelCreate,
    user_id: str = Depends(_owner),
    db: AsyncSession = Depends(get_db),
):
    return await _call(RecordingService(db).create_channel(user_id, payload))


@router.get("/channels", response_model=ChannelList)
async def list_channels(
    user_id: str = Depends(_owner),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await _call(RecordingService(db).list_channels(user_id, limit, offset))


@router.get("/channels/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: str,
    user_id: str = Depends(_owner),
    db: AsyncSession = Depends(get_db),
):
    return await _call(RecordingService(db).get_channel(user_id, channel_id))


@router.patch("/channels/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: str,
    payload: ChannelUpdate,
    user_id: str = Depends(_owner),
    db: AsyncSession = Depends(get_db),
):
    return await _call(RecordingService(db).update_channel(user_id, channel_id, payload))


@router.post("/channels/{channel_id}/sessions", response_model=SessionResponse, status_code=201)
async def register_session(
    channel_id: str,
    payload: SessionCreate,
    response: Response,
    user_id: str = Depends(_owner),
    db: AsyncSession = Depends(get_db),
):
    session, created = await _call(
        RecordingService(db).register_session(user_id, channel_id, payload)
    )
    response.status_code = 201 if created else 200
    return session


@router.get("/channels/{channel_id}/sessions", response_model=SessionList)
async def list_sessions(
    channel_id: str,
    user_id: str = Depends(_owner),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await _call(
        RecordingService(db).list_sessions(user_id, channel_id, limit, offset)
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    user_id: str = Depends(_owner),
    db: AsyncSession = Depends(get_db),
):
    return await _call(RecordingService(db).get_session(user_id, session_id))


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    payload: SessionUpdate,
    user_id: str = Depends(_owner),
    db: AsyncSession = Depends(get_db),
):
    return await _call(RecordingService(db).update_session(user_id, session_id, payload))
