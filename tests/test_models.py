"""Content vs Publication: what a content inherits from its publications."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from creatorvault.models import META_DRAFT, Content, Post, Publication


def pub(day: int, caption: str = "", tier: str | None = None, **kw) -> Publication:
    return Publication(
        key=str(day), timestamp=datetime(2024, 1, day, tzinfo=UTC), caption=caption, tier=tier, **kw
    )


def test_post_alias():
    assert Post is Publication


def test_content_inherits_best_and_latest():
    old = pub(1, "First caption", "average", metrics={"engagement": 10}, media=[Path("a.jpg")])
    top = pub(5, "", "top", metrics={"engagement": 5})
    draft = pub(9, "Draft caption", source=META_DRAFT, draft_id="d1", media=[Path("d.jpg")])
    c = Content([top, draft, old])

    assert c.first is old and c.published == [old, top] and c.drafts == [draft]
    assert c.best is top and c.best_tier == "top" and c.best_engagement == 10
    assert c.caption == "First caption"  # latest non-empty export caption beats the draft
    assert c.media == [Path("a.jpg")]
    assert c.status == "published+draft"
    assert c.title == "First caption"
    assert c.id == Content([old]).id  # keyed on the first publication


def test_status_and_fallbacks():
    draft = pub(3, "", source=META_DRAFT, draft_id="d")
    c = Content([draft])
    assert c.status == "draft" and c.first is draft
    assert c.best_engagement is None and c.media == [] and c.caption == ""
    assert c.title == "Post from 2024-01-03"
    assert Content([pub(1, "x", match_note="check")]).match_note == "check"
    assert Content([pub(1)]).status == "published"
