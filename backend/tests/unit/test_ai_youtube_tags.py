import pytest

from src import ai
from src.workflows import schemas


def test_highlight_response_keeps_clean_tags_and_reads_older_responses():
    base={"start_time":"00:00","end_time":"00:30","text":"GTA 6 in Vice City"}
    segment=ai.TranscriptSegment(**base,youtube_tags=["#GTA6","Vice City","vice city"])
    assert segment.youtube_tags == ["GTA6","Vice City"]
    assert ai.TranscriptSegment(**base).youtube_tags == []
    prompt=ai.build_transcript_system_prompt()
    assert "youtube_tags" in prompt and "guessed identities" in prompt


@pytest.mark.parametrize("schema",[schemas.PartCopy,schemas.TopicMoment,schemas.RecapDraft,schemas.TrailerDraft])
def test_each_workflow_gets_tag_suggestions_in_its_existing_model_response(schema):
    assert "youtube_tags" in schema.model_fields
    assert "youtube_tags" in schema.model_json_schema()["required"]
