import pytest
from pydantic import ValidationError



@pytest.mark.parametrize(("platform", "handle", "expected"), [("twitch", " Demo_123 ", "demo_123"), ("kick", "Demo-123", "demo-123"), ("youtube", " @Créateur日本 ", "créateur日本")])
def test_normalizes_bare_platform_identity(platform, handle, expected):
    from src.recording.schemas import ChannelCreate
    value = ChannelCreate(platform=platform, handle=handle, name=" Demo ")
    assert value.handle == expected and value.name == "Demo"
    assert value.quality == "best"


@pytest.mark.parametrize(("platform", "handle"), [("twitch", "https://twitch.tv/demo"), ("kick", "demo/path"), ("youtube", "@a?token=x"), ("twitch", "demo\n"), ("kick", "demo#live"), ("youtube", "@"), ("youtube", "ab"), ("twitch", "a" * 26), ("kick", "a" * 26), ("youtube", "a" * 31), ("twitch", "démo"), ("youtube", "a b c"), ("youtube", "@@demo"), ("youtube", "a\u200bb"), ("vimeo", "demo")])
def test_rejects_url_path_control_or_invalid_platform_handle(platform, handle):
    from src.recording.schemas import ChannelCreate
    with pytest.raises(ValidationError):
        ChannelCreate(platform=platform, handle=handle, name="Demo")


@pytest.mark.parametrize("quality", ["--output", "best;rm", "$(id)", "../best", "best\n", "best,,worst", "", "best / worst", "best?x=y", "a" * 256])
def test_quality_cannot_be_a_flag_path_or_command(quality):
    from src.recording.schemas import ChannelCreate
    with pytest.raises(ValidationError):
        ChannelCreate(platform="kick", handle="demo", name="Demo", quality=quality)


def test_quality_supports_simple_stream_fallback_names():
    from src.recording.schemas import ChannelCreate
    value = ChannelCreate(platform="youtube", handle="demo", name="Demo", quality="1080p60,720p,best")
    assert value.quality == "1080p60,720p,best"


@pytest.mark.parametrize("external_id", ["", "x\ny", "\x00", "x" * 256, "\u200b", 3])
def test_registration_requires_bounded_printable_external_identity(external_id):
    from src.recording.schemas import SessionCreate
    with pytest.raises(ValidationError):
        SessionCreate(external_id=external_id)
