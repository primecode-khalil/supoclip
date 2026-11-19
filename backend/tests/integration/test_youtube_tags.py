"""Generated tag suggestions become explicit, immutable approval metadata."""
import json

import pytest
from sqlalchemy import text

from tests.integration.test_social_review import review_item  # noqa: F401
from tests.integration.test_social_publishing import social_setup  # noqa: F401
from tests.unit.test_social_publication_policy import short_file  # noqa: F401


@pytest.mark.parametrize("edited,expected", [(None, ["GTA 6", "Vice City"]),
    ([], []), (["#GTA 6", "Car chase", "car CHASE"], ["GTA 6", "Car chase"])])
async def test_review_tags_default_edit_clear_and_freeze(review_item, client, auth_headers, db_session, edited, expected):
    item, payload, _, _ = review_item
    await db_session.execute(text("UPDATE generated_clips SET text=:text,workflow_meta=CAST(:meta AS jsonb) WHERE id=:id"),
        {"id": payload["clip_id"], "text": "A car chase in GTA 6 through Vice City.",
         "meta": json.dumps({"youtube_tags": ["GTA 6", "Vice City", "Minecraft", "viral"]})})
    await db_session.commit()
    listing = await client.get(f"/social/review?account_id={payload['social_account_id']}", headers=auth_headers)
    current = listing.json()["items"][0]
    assert current["youtube_tags"] == ["GTA 6", "Vice City"]
    body = {"expected_version": current["version"], "caption": "Owner description", "hashtags": ["MySeries"]}
    if edited is not None:
        body["youtube_tags"] = edited
    response = await client.post(f"/social/review/{item['id']}/approve", headers=auth_headers, json=body)
    assert response.status_code == 200, response.text
    post = response.json()["post"]
    assert post["provider_options"]["youtube_tags"] == expected
    assert post["hashtags"] == ["MySeries"]
    # Later source metadata edits and repeated approval cannot change frozen tags.
    await db_session.execute(text("UPDATE generated_clips SET workflow_meta=CAST(:meta AS jsonb) WHERE id=:id"),
        {"id": payload["clip_id"], "meta": json.dumps({"youtube_tags": ["Different"]})})
    await db_session.commit()
    again = await client.post(f"/social/review/{item['id']}/approve", headers=auth_headers,
        json={"expected_version": current["version"], "youtube_tags": ["Changed"]})
    assert again.status_code == 200
    assert again.json()["post"]["provider_options"]["youtube_tags"] == expected
    assert again.json()["item"]["youtube_tags"] == expected


@pytest.mark.parametrize("tags", [["x"] * 9, ["x" * 61], "not a list"])
async def test_review_rejects_invalid_tag_input(review_item, client, auth_headers, tags):
    item, _, _, _ = review_item
    response = await client.post(f"/social/review/{item['id']}/approve", headers=auth_headers,
        json={"expected_version": item["version"], "youtube_tags": tags})
    assert response.status_code == 422
