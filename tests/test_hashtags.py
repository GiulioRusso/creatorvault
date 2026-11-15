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


@pytest.mark.parametrize("strategy", ["fixed", "keep_original", "taxonomy"])
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
    [({"strategy": "random"}, "must be one of"), ({"maxx": 3}, "Unknown hashtags option")],
)
def test_bad_config(raw, message):
    with pytest.raises(SystemExit, match=message):
        HashtagConfig.from_dict(raw)


def test_note_flags_too_many_hashtags(tmp_path):
    p = Publication(key="1", timestamp=datetime(2024, 1, 1, tzinfo=UTC), caption=CAPTIONS[1])
    content = Content([p])
    content.ready_caption = ready_caption(content.caption, {}, HashtagConfig())
    write_notes([content], tmp_path, "attachments", max_hashtags=5)
    (note,) = (tmp_path / "posts").glob("*.md")
    text = note.read_text()
    assert "hashtags_original_count: 10" in text and "  - lint/too-many-hashtags" in text
    assert "## Ready to post" in text and "## Original caption" in text
