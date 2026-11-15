"""Hashtags: split them off the caption and build a ready-to-post caption
with at most `max` of them (Instagram rejects scheduled/API posts with more)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from typing import Any

HASHTAG = re.compile(r"#(\w+)")
STRATEGIES = ("fixed", "keep_original", "taxonomy")
DEFAULT_FIXED = ["#history", "#space", "#moon", "#exploration", "#science"]


@dataclass
class HashtagConfig:
    max: int = 5
    strategy: str = "fixed"
    fixed: list[str] = field(default_factory=lambda: list(DEFAULT_FIXED))
    taxonomy: dict[str, str] = field(default_factory=dict)  # "program/apollo" -> "#apollo"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> HashtagConfig:
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise SystemExit(f"[!] Unknown hashtags option(s): {', '.join(sorted(unknown))}")
        cfg = cls(**raw)
        if cfg.strategy not in STRATEGIES:
            raise SystemExit(
                f"[!] hashtags.strategy must be one of {', '.join(STRATEGIES)}, "
                f"not '{cfg.strategy}'"
            )
        return cfg


def unique(tags: list[str]) -> list[str]:
    """'#'-prefixed, case-insensitively deduplicated, order kept."""
    seen: set[str] = set()
    out = []
    for tag in tags:
        tag = "#" + tag.strip().lstrip("#")
        if len(tag) > 1 and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out


def split_caption(caption: str) -> tuple[str, list[str]]:
    """(body, hashtags). The body has no hashtags left: trailing runs are
    dropped, inline ones become plain words, so the ready caption can't
    exceed the limit by accident. Trailing spacer lines (".") go too."""
    tags = unique(HASHTAG.findall(caption))
    lines = []
    for line in caption.splitlines():
        line = re.sub(r"(?:\s*#\w+)+\s*$", "", line)
        lines.append(" ".join(HASHTAG.sub(r"\1", line).split()))
    while lines and re.fullmatch(r"[.·•\s]*", lines[-1]):
        lines.pop()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip(), tags


def choose(original: list[str], tags: dict[str, list[str]], cfg: HashtagConfig) -> list[str]:
    if cfg.strategy == "keep_original":
        pool = original
    elif cfg.strategy == "taxonomy":
        mapped = [
            cfg.taxonomy[f"{axis}/{v}"]
            for axis, values in tags.items()
            for v in values
            if f"{axis}/{v}" in cfg.taxonomy
        ]
        pool = mapped + cfg.fixed
    else:
        pool = cfg.fixed
    return unique(pool)[: cfg.max]


def ready_caption(caption: str, tags: dict[str, list[str]], cfg: HashtagConfig) -> str:
    body, original = split_caption(caption)
    chosen = choose(original, tags, cfg)
    return f"{body}\n.\n{' '.join(chosen)}" if chosen else body
