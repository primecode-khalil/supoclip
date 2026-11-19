"""A retried recorder publication must resolve the same durable post."""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from tests.integration.test_social_publishing import social_setup  # noqa: F401


async def test_keyed_post_replays_and_rejects_changed_intent(
    social_setup, client, auth_headers, db_session,
):
    _, payload = social_setup
    payload["scheduled_for"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    headers = {**auth_headers, "Idempotency-Key": "recording:window:clip:account"}
    responses = await asyncio.gather(*(
        client.post("/social/posts", headers=headers, json=payload) for _ in range(3)
    ))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert len({r.json()["post"]["id"] for r in responses}) == 1
    post_id = responses[0].json()["post"]["id"]
    await db_session.execute(text("UPDATE social_posts SET status='failed' WHERE id=:id"), {"id": post_id})
    await db_session.commit()
    replay = await client.post("/social/posts", headers=headers, json=payload)
    assert replay.json()["post"]["id"] == post_id
    assert replay.json()["post"]["status"] == "failed"
    conflict = await client.post("/social/posts", headers=headers, json={**payload, "title": "Changed intent"})
    assert conflict.status_code == 409


async def test_deleted_history_preserves_publication_tombstone(social_setup, client, auth_headers, db_session):
    _, payload = social_setup
    payload["scheduled_for"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    headers = {**auth_headers, "Idempotency-Key": "recording:lost-response-deleted-post"}
    first = await client.post("/social/posts", headers=headers, json=payload)
    post_id = first.json()["post"]["id"]
    # The supervisor may have died before it received first's response. Deleting
    # UI history cannot mean that the external publication never happened.
    await db_session.execute(text("DELETE FROM social_posts WHERE id=:id"), {"id": post_id})
    await db_session.commit()
    replay = await client.post("/social/posts", headers=headers, json=payload)
    assert replay.status_code == 410
    assert (await db_session.execute(text("SELECT count(*) FROM social_posts WHERE task_id=:task"), {"task": payload["task_id"]})).scalar_one() == 0
