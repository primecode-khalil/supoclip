import asyncio
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import text

from src.database import AsyncSessionLocal
from tests.integration.test_social_publishing import social_setup  # noqa: F401


@pytest.fixture
async def review_policy(social_setup, client, auth_headers, db_session):
    _, payload = social_setup
    account = payload["social_account_id"]
    response = await client.put(f"/social/accounts/{account}/automation", headers=auth_headers, json={
        "mode": "review", "timezone": "UTC", "schedule": {"kind": "interval", "interval_minutes": 360, "anchor_at": "2026-11-20T00:00:00Z"},
    })
    assert response.status_code == 200, response.text
    return account, payload


async def test_policy_defaults_and_owner_boundaries(social_setup, client, auth_headers):
    _, payload = social_setup
    url = f"/social/accounts/{payload['social_account_id']}/automation"
    assert (await client.get(url)).status_code == 401
    result = await client.get(url, headers=auth_headers)
    assert result.status_code == 200
    assert result.json()["policy"]["mode"] == "review"
    assert result.json()["policy"]["schedule"]["interval_minutes"] == 360
    assert (await client.get("/social/accounts/missing/automation", headers=auth_headers)).status_code == 404
    assert (await client.put(url, headers=auth_headers, json={"timezone": "Not/AZone"})).status_code == 422


async def test_automatic_approval_requires_private_proof(social_setup, client, auth_headers):
    _, payload = social_setup
    response = await client.put(f"/social/accounts/{payload['social_account_id']}/automation", headers=auth_headers, json={"mode": "automatic"})
    assert response.status_code == 400
    assert "private" in response.text.lower()


async def test_reservations_are_shared_and_concurrent_approvals_do_not_collide(review_policy, db_session):
    from src.repositories.social_publication_policy_repository import SocialPublicationPolicyRepository as Policies
    from src.repositories.social_review_repository import SocialReviewRepository as Reviews
    from src.services.social_publication_policy import reserve_publication_slot

    account, payload = review_policy
    # Separate review items model clips arriving from different sources.
    rows = []
    for index in range(4):
        from tests.fixtures.factories import create_source, create_task, create_clip
        source = await create_source(db_session)
        task = await create_task(db_session, user_id="user-1", source_id=source["id"])
        clip = await create_clip(db_session, task_id=task["id"])
        row = await Reviews.add(db_session, "user-1", account, task["id"], clip["id"], f"render-{index}", f"/fixture/{index}.mp4", source_key=f"source-{index}")
        rows.append(row)
    now = datetime(2026, 11, 20, 0, 1, tzinfo=timezone.utc)

    async def reserve(review_id):
        async with AsyncSessionLocal() as other:
            return await reserve_publication_slot(other, review_id, now)

    slots = sorted(await asyncio.gather(*(reserve(row["id"]) for row in rows)))
    assert slots == [datetime(2026, 11, 20, hour, tzinfo=timezone.utc) for hour in (6, 12, 18)] + [datetime(2026, 11, 21, 0, tzinfo=timezone.utc)]
    assert await reserve(rows[0]["id"]) in slots
    assert (await db_session.execute(text("SELECT count(*) FROM social_publication_slots WHERE account_id=:id"), {"id": account})).scalar_one() == 4


async def test_policy_edits_do_not_move_existing_approvals(review_policy, db_session, client, auth_headers):
    from src.repositories.social_review_repository import SocialReviewRepository as Reviews
    from src.services.social_publication_policy import reserve_publication_slot

    account, payload = review_policy
    row = await Reviews.add(db_session, "user-1", account, payload["task_id"], payload["clip_id"], "original", "/fixture.mp4")
    now = datetime(2026, 11, 20, 0, 1, tzinfo=timezone.utc)
    original = await reserve_publication_slot(db_session, row["id"], now)
    response = await client.put(f"/social/accounts/{account}/automation", headers=auth_headers, json={"schedule": {"interval_minutes": 60, "anchor_at": "2026-11-20T00:00:00Z"}})
    assert response.status_code == 200
    assert await reserve_publication_slot(db_session, row["id"], now) == original
