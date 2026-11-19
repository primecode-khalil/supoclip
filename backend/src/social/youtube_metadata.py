"""YouTube's metadata limits and owner-selected upload declarations."""
from __future__ import annotations

import re

from .base import PublishRequest, SocialProviderError
from ..publishing_tags import normalize_youtube_tags


def _clean(value: str) -> str:
    return value.replace("<", "").replace(">", "").replace("\x00", "").strip()


def build_youtube_metadata(request: PublishRequest) -> dict:
    options = request.provider_options
    category = options.get("category_id", "22")
    if not isinstance(category, str) or not re.fullmatch(r"[0-9]{1,3}", category):
        raise SocialProviderError("Choose a valid YouTube category.")
    audience = options.get("made_for_kids", False)
    disclosure = options.get("contains_synthetic_media")
    if type(audience) is not bool or (disclosure is not None and type(disclosure) is not bool):
        raise SocialProviderError("YouTube audience and disclosure must be explicit yes/no choices.")
    tags = normalize_youtube_tags(options.get("youtube_tags", request.hashtags))
    hashtags = []
    for raw in request.hashtags:
        tag = re.sub(r"\s+", "", _clean(str(raw)).lstrip("#"))
        if not tag or any(tag.casefold() == old.casefold() for old in hashtags):
            continue
        candidate = " ".join("#" + item for item in [*hashtags, tag])
        if len(candidate.encode("utf-8")) <= 4998:
            hashtags.append(tag)
    hashtag_text = " ".join("#" + tag for tag in hashtags)
    caption = _clean(request.caption or "")
    room = 5000 - len(hashtag_text.encode("utf-8")) - (2 if caption and hashtag_text else 0)
    caption = caption.encode("utf-8")[:max(0, room)].decode("utf-8", errors="ignore").rstrip()
    description = "\n\n".join(part for part in (caption, hashtag_text) if part)
    status = {
        "privacyStatus": request.privacy_level if request.privacy_level in ("private", "public", "unlisted") else "private",
        "selfDeclaredMadeForKids": audience,
    }
    if options.get("native_schedule") is True:
        # Scheduling is a separate, verified step after private processing.
        status["privacyStatus"] = "private"
    if disclosure is not None:
        status["containsSyntheticMedia"] = disclosure
    return {
        "snippet": {
            "title": _clean(request.title or "")[:100] or "Untitled clip",
            "description": description,
            "tags": tags,
            "categoryId": category,
        },
        "status": status,
    }
