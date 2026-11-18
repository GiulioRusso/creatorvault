"""Hashtags: never more than `max` in a ready caption."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from creatorvault.hashtags import HASHTAG, HashtagConfig, ready_caption, split_caption
from creatorvault.models import Content, Publication
from creatorvault.writers.obsidian import write_notes

CAPTIONS = [
    "Apollo 11 lands on the Moon\nThe Eagle has landed. #apollo #space",
    "Happy #valentines from the #moon 🚀\n.\n.\n.\n#a #b #c #d #e #f #g #h #A",
    "#only #hashtags",
    "",
    "No tags at all",
]
TAGS = {"program": ["apollo"], "angle": ["photo", "quote"]}


def test_split_caption():
    body, tags = split_caption(CAPTIONS[1])
    assert body == "Happy valentines from the moon 🚀"
    assert tags == ["#valentines", "#moon", "#a", "#b", "#c", "#d", "#e", "#f", "#g", "#h"]
    assert split_caption("  spaced   out  \n\n\n\nnext\n. ") == ("spaced out\n\nnext", [])


@pytest.mark.parametrize("strategy", ["fixed", "keep_original", "taxonomy", "pool"])
@pytest.mark.parametrize("caption", CAPTIONS)
def test_never_more_than_max(strategy, caption):
    cfg = HashtagConfig(
        max=3, strategy=strategy, taxonomy={"program/apollo": "apollo", "angle/photo": "#Photo"}
    )
    ready = ready_caption(caption, TAGS, cfg)
    assert len(HASHTAG.findall(ready)) <= 3


def test_strategies():
    keep = HashtagConfig(strategy="keep_original")
    assert ready_caption(CAPTIONS[1], {}, keep).endswith("\n.\n#valentines #moon #a #b #c")

    tax = HashtagConfig(strategy="taxonomy", taxonomy={"program/apollo": "#apollo"})
    assert ready_caption("Hi", TAGS, tax) == "Hi\n.\n#apollo #history #space #moon #exploration"
    assert ready_caption("Hi", {}, tax) == "Hi\n.\n#history #space #moon #exploration #science"

    assert ready_caption("Hi #x", {}, HashtagConfig(fixed=[])) == "Hi"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"strategy": "random"}, "must be one of"),
        ({"maxx": 3}, "Unknown hashtags option"),
        ({"max": 6}, "between 0 and 5"),
        ({"max": -1}, "between 0 and 5"),
        ({"max": True}, "between 0 and 5"),
        ({"pool": "space moon"}, "list of individual"),
        ({"pool": ["#space #moon"]}, "list of individual"),
    ],
)
def test_bad_config(raw, message):
    with pytest.raises(SystemExit, match=message):
        HashtagConfig.from_dict(raw)


def test_note_keeps_only_prepared_description(tmp_path):
    p = Publication(key="1", timestamp=datetime(2024, 1, 1, tzinfo=UTC), caption=CAPTIONS[1])
    content = Content([p])
    content.ready_caption = ready_caption(content.caption, {}, HashtagConfig())
    write_notes([content], tmp_path, {content.id: "slug"})
    (note,) = (tmp_path / "archive").glob("*.md")
    text = note.read_text()
    assert "hashtags_original_count" not in text and "lint/too-many-hashtags" not in text
    assert "## Description" in text and "## Original caption" not in text
    assert CAPTIONS[1] not in text and text.count("```text") == 1


def test_pool_ignores_original_hashtags_and_varies_stably():
    cfg = HashtagConfig.from_dict(
        {
            "strategy": "pool",
            "pool": ["space", "nasa", "history", "science", "moon", "astronauts", "exploration"],
        }
    )
    first = ready_caption("Moon landing\n#old #unrelated #original", {}, cfg)
    assert first == ready_caption("Moon landing\n#other", {}, cfg)
    assert first == ready_caption("Moon landing", {}, cfg)
    selected = HASHTAG.findall(first)
    assert len(selected) == len(set(selected)) == 5
    assert set(selected) <= set(cfg.pool)
    variants = {
        tuple(HASHTAG.findall(ready_caption(f"Space story {i}", {}, cfg))) for i in range(10)
    }
    assert len(variants) > 1


def test_pool_handles_short_empty_and_duplicate_lists():
    cfg = HashtagConfig.from_dict({"strategy": "pool", "pool": ["space", "#SPACE", "#nasa"]})
    assert len(HASHTAG.findall(ready_caption("Hello #old", {}, cfg))) == 2
    cfg.pool = []
    assert ready_caption("Hello #old", {}, cfg) == "Hello"
    cfg.pool = ["space"]
    cfg.max = 0
    assert ready_caption("Hello #old", {}, cfg) == "Hello"
