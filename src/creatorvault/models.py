"""Post data model and shared logging."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass
class Post:
    key: str                        # stable identifier, derived from the timestamp
    timestamp: datetime             # UTC
    caption: str
    media: list[Path] = field(default_factory=list)   # absolute paths inside the export
    metrics: dict[str, float] = field(default_factory=dict)
    tags: dict[str, list[str]] = field(default_factory=dict)
    permalink: str | None = None
    tier: str | None = None
    match_note: str | None = None   # warnings about the join

    @property
    def is_carousel(self) -> bool:
        return len(self.media) > 1

    @property
    def title(self) -> str:
        first_line = self.caption.strip().splitlines()[0] if self.caption.strip() else ""
        first_line = re.sub(r"#\S+", "", first_line).strip()
        if not first_line:
            return self.timestamp.strftime("Post from %Y-%m-%d")
        return first_line[:70]
