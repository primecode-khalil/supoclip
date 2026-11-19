"""Small keyword sets, with conservative transcript grounding for AI suggestions."""
from __future__ import annotations

import re
import unicodedata

MAX_YOUTUBE_TAGS = 8
MAX_YOUTUBE_TAG_LENGTH = 60
YOUTUBE_TAG_INSTRUCTIONS = """For each youtube_tags field, suggest 3-6 useful YouTube
keywords copied from that clip's own spoken content, at most 8 and 60 characters
each. Prefer specific subjects, names and short multiword phrases. Keep the
clip's language. Use fewer or [] when uncertain. Never infer a person, game or
place from other parts of the source. No guessed identities, generic promotional
tags (viral, trending, fyp, Shorts), duplicate variants, emojis or hashtags.
Tags describe only the selected cut, including when the cut changes."""
_PROMOTIONAL = {"viral", "trending", "fyp", "for you", "foryou", "shorts", "youtube shorts", "ytshorts", "subscribe", "must watch", "watch till end"}


def normalize_youtube_tags(raw: object) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    result, seen, used = [], set(), 0
    for value in raw:
        if not isinstance(value, str):
            continue
        tag = unicodedata.normalize("NFKC", value)
        tag = " ".join(re.sub(r"[<>\x00-\x1f\x7f,]", " ", tag).split()).lstrip("#").strip().strip('"“”')
        key = tag.casefold()
        if not tag or len(tag) > MAX_YOUTUBE_TAG_LENGTH or key in seen:
            continue
        cost = len(tag) + (2 if " " in tag else 0) + bool(result)
        if used + cost > 500:
            continue
        result.append(tag)
        seen.add(key)
        used += cost
        if len(result) == MAX_YOUTUBE_TAGS:
            break
    return result


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())


def ground_youtube_tags(raw: object, transcript: str) -> list[str]:
    """Drop generated terms absent from this cut; owner edits are not constrained."""
    if not isinstance(raw, (list, tuple)) or not transcript:
        return []
    words = _words(transcript)
    heard = set(words)
    # The Arabic conjunction/preposition can be attached to a definite noun.
    heard.update(word[1:] for word in words if len(word) > 4 and word[:1] in {"و", "ف", "ب"} and word[1:3] == "ال")
    # Keep spellings such as GTA6/OpenAI when the transcript has GTA 6/Open AI.
    joined = {"".join(words[i:i+n]) for i in range(len(words)) for n in range(1, 5)}
    candidates = []
    for value in raw:
        clean = normalize_youtube_tags([value])
        if not clean or clean[0].casefold() in _PROMOTIONAL:
            continue
        tag = clean[0]
        tokens = _words(tag)
        if tokens and (all(word in heard for word in tokens) or "".join(tokens) in joined):
            candidates.append(tag)
    return normalize_youtube_tags(candidates)
