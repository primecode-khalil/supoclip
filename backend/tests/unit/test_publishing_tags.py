"""Small, grounded metadata suggestions; no generic promotional filler."""
from src.publishing_tags import ground_youtube_tags, normalize_youtube_tags


def test_normalizes_phrases_unicode_and_duplicates_without_guessing():
    assert normalize_youtube_tags([" #GTA 6 ", "gta 6", "  Vice   City ", "زواج", "زواج", 123, "", "x"*61]) == ["GTA 6", "Vice City", "زواج"]


def test_caps_count_and_aggregate_budget_including_space_quotes():
    tags=normalize_youtube_tags([f"word {n} "+"x"*53 for n in range(15)])
    assert 1 <= len(tags) <= 8
    assert sum(len(tag)+(2 if " " in tag else 0) for tag in tags)+len(tags)-1 <= 500


def test_grounds_generated_names_and_topics_in_this_clip_only():
    text="In GTA 6 we drove through Vice City. This is a police chase."
    assert ground_youtube_tags(["GTA6", "Vice City", "police chase", "iShowSpeed", "Minecraft", "viral", "FYP", "Shorts"],text) == ["GTA6", "Vice City", "police chase"]


def test_does_not_match_keywords_inside_unrelated_words_and_keeps_language():
    assert ground_youtube_tags(["cat", "educational"],"An educational video") == ["educational"]
    assert ground_youtube_tags(["الزواج", "العلاقات", "gaming"],"نتحدث عن الزواج والعلاقات") == ["الزواج", "العلاقات"]


def test_empty_or_malformed_suggestions_are_safe():
    for raw in (None, "viral, gaming", {"tag":"GTA6"}, 123):
        assert normalize_youtube_tags(raw) == []
    assert ground_youtube_tags(["GTA6"],"") == []
