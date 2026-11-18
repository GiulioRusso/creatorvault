"""Data model (one Content, one or more Publications) and shared logging."""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Everything logged during a run, saved as <out>/run.log by build.
RUN_LOG: list[str] = []


def log(msg: str) -> None:
    RUN_LOG.append(msg)
    print(msg, file=sys.stderr)


INSTAGRAM = "instagram_export"
META_DRAFT = "meta_draft"


@dataclass
class Publication:
    """One time a content went out (or is waiting to, as a Meta draft)."""

    key: str  # stable identifier, derived from the timestamp (or the draft id)
    timestamp: datetime  # UTC
    caption: str
    media: list[Path] = field(default_factory=list)  # absolute paths inside the export
    metrics: dict[str, float] = field(default_factory=dict)
    tags: dict[str, list[str]] = field(default_factory=dict)
    permalink: str | None = None
    top_percent: int | None = None  # in the top N% of its year; None = no metrics
    source: str = INSTAGRAM
    draft_id: str | None = None
    content_type: str = "posts"  # posts | reels; determined by export metadata, not file extension

    @property
    def is_carousel(self) -> bool:
        return len(self.media) > 1

    @property
    def title(self) -> str:
        return caption_title(self.caption, self.timestamp)


Post = Publication  # v0.1 name, kept for compatibility


def caption_title(caption: str, timestamp: datetime) -> str:
    first_line = caption.strip().splitlines()[0] if caption.strip() else ""
    first_line = re.sub(r"#\S+", "", first_line).strip()
    if not first_line:
        return timestamp.strftime("Post from %Y-%m-%d")
    return first_line[:70]


@dataclass
class Content:
    """A piece of content and every time it was published (reposts included)."""

    publications: list[Publication]
    tags: dict[str, list[str]] = field(default_factory=dict)
    photo_ids: list[str] = field(default_factory=list)
    ready_caption: str = ""  # cleaned caption + at most hashtags.max hashtags

    @property
    def published(self) -> list[Publication]:
        return sorted(
            (p for p in self.publications if p.source == INSTAGRAM), key=lambda p: p.timestamp
        )

    @property
    def drafts(self) -> list[Publication]:
        return sorted(
            (p for p in self.publications if p.source == META_DRAFT), key=lambda p: p.timestamp
        )

    @property
    def first(self) -> Publication:
        """First publication (or oldest draft): it names the note, so the
        filename stays stable as reposts get added."""
        return (self.published or self.drafts)[0]

    @property
    def id(self) -> str:
        return hashlib.sha1(self.first.key.encode()).hexdigest()[:12]

    @property
    def status(self) -> str:
        if self.published and self.drafts:
            return "published+draft"
        return "published" if self.published else "draft"

    @property
    def best(self) -> Publication:
        """Best-performing publication: best rank, then engagement."""
        return min(
            self.publications,
            key=lambda p: (p.top_percent or 101, -p.metrics.get("engagement", 0)),
        )

    @property
    def top_percent(self) -> int | None:
        return self.best.top_percent

    @property
    def best_engagement(self) -> float | None:
        values = [p.metrics["engagement"] for p in self.publications if "engagement" in p.metrics]
        return max(values) if values else None

    def _latest(self, attr: str) -> Publication | None:
        """Latest publication with a non-empty attr; the export wins over drafts."""
        found = [p for p in self.publications if getattr(p, attr)]
        return max(found, key=lambda p: (p.source == INSTAGRAM, p.timestamp), default=None)

    @property
    def caption(self) -> str:
        latest = self._latest("caption")
        return latest.caption if latest else ""

    @property
    def media(self) -> list[Path]:
        latest = self._latest("media")
        return latest.media if latest else []

    @property
    def title(self) -> str:
        return caption_title(self.caption, self.first.timestamp)
