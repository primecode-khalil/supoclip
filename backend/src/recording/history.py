"""Retain recovery identities when an owner clears recording activity."""
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .automation_models import RecordingWindow
from .errors import RecordingError, WindowClearedError


def visible_history():
    return ~RecordingWindow.details.contains({"history_cleared": True})


async def recording_window_for_task(db: AsyncSession, user_id: str, request_key: str, upload_ref: str) -> str | None:
    """Attach recorder provenance in the task's initial insert, before binding."""
    match = re.fullmatch(r"recording:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}):task", request_key)
    if match is None:
        return None
    row = (await db.execute(text("""
        SELECT w.id, w.metadata @> jsonb_build_object('history_cleared', true) AS cleared
        FROM recording_windows w JOIN recording_channels c ON c.id = w.channel_id
        WHERE w.id = :id AND c.user_id = :owner AND w.upload_ref = :upload_ref
    """), {"id": match[1], "owner": user_id, "upload_ref": upload_ref})).first()
    if row is None:
        raise RecordingError("Recording window not found", 404)
    if row.cleared:
        raise WindowClearedError()
    return row.id


async def clear_deleted_task_history(db: AsyncSession, task_id: str) -> None:
    """Participate in task deletion's transaction, before ON DELETE SET NULL."""
    await db.execute(text("""
        UPDATE recording_windows w
        SET metadata = w.metadata || jsonb_build_object(
                'history_cleared', true,
                'history_cleared_reason', 'task_deleted',
                'history_cleared_at', clock_timestamp()),
            status = CASE WHEN w.status = 'completed' THEN w.status ELSE 'blocked' END,
            next_attempt_at = NULL, last_error = NULL, updated_at = clock_timestamp()
        FROM tasks t, recording_channels c
        WHERE t.id = :task_id AND c.id = w.channel_id AND c.user_id = t.user_id
          AND (w.task_id = t.id OR w.id = t.source_metadata->>'recording_window_id')
    """), {"task_id": task_id})
