"""YouTube's metadata limits and owner-selected upload declarations."""
from __future__ import annotations

import re

from .base import PublishRequest, SocialProviderError


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
    tags, used = [], 0
    for raw in [*request.hashtags, "Shorts"]:
        tag = _clean(str(raw)).lstrip("#").strip()
        if not tag or any(tag.lower() == old.lower() for old in tags):
            continue
        cost = len(tag) + (2 if " " in tag else 0) + bool(tags)
        if used + cost <= 500 and len(tags) < 30:
            tags.append(tag)
            used += cost
    hashtag_text = " ".join("#" + re.sub(r"\s+", "", tag) for tag in tags)
    if not any(tag.lower() == "shorts" for tag in tags):
        hashtag_text += " #Shorts"
    caption = _clean(request.caption or "")
    room = 5000 - len(hashtag_text.encode("utf-8")) - (2 if caption else 0)
    caption = caption.encode("utf-8")[:max(0, room)].decode("utf-8", errors="ignore").rstrip()
    description = f"{caption}\n\n{hashtag_text}" if caption else hashtag_text
    status = {
        "privacyStatus": request.privacy_level if request.privacy_level in ("private", "public", "unlisted") else "private",
        "selfDeclaredMadeForKids": audience,
    }
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
