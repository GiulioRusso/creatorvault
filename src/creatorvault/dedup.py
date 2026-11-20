"""Repost detection: groups publications of the same content into one Content.

Signals, strongest first, combined with a union-find:
1. photo code in the caption, from dedup.photo_id_patterns (same code = same
   content; two different codes = never the same content, whatever else matches);
2. dHash of the first image (needs the optional Pillow dependency);
3. normalized caption similarity, SequenceMatcher ratio (>= caption_same merges; between
   caption_maybe and caption_same is a candidate for the local reviewer,
   kept separate without one).
Manual decisions live in dedup_overrides.yaml (merge / split).
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field, fields
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

from creatorvault.models import Content, Publication, log

# Whole lines (case-insensitive) dropped before comparing captions.
DEFAULT_BOILERPLATE = [r"check (the )?link in (my |our )?bio.*", r"[.\s]+"]
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}

# Below this, any two captions on the same topic look alike: measured on a
# real 2k-post archive, ~15% of random pairs score >= 0.50.
MIN_CAPTION_THRESHOLD = 0.60
# Word-overlap prefilter: on that archive no pair with similarity >= 0.60 had
# a word Dice below 0.33, and the filter skips ~94% of the full comparisons.
MIN_WORD_DICE = 0.30


@dataclass
class DedupConfig:
    enabled: bool = True
    image_distance: int = 6
    caption_same: float = 0.85
    caption_maybe: float = 0.70
    # Regexes for photo/catalogue codes quoted in captions; none by default.
    photo_id_patterns: list[str] = field(default_factory=list)
    boilerplate: list[str] = field(default_factory=lambda: list(DEFAULT_BOILERPLATE))
    overrides: Path = Path("config/dedup_overrides.yaml")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DedupConfig:
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise SystemExit(f"[!] Unknown dedup option(s): {', '.join(sorted(unknown))}")
        cfg = cls(**raw)
        for name in ("caption_same", "caption_maybe"):
            value = getattr(cfg, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise SystemExit(f"[!] dedup.{name} must be a number between 0 and 1 (75% = 0.75).")
        if cfg.caption_maybe < MIN_CAPTION_THRESHOLD:
            raise SystemExit(
                f"[!] dedup.caption_maybe must be >= {MIN_CAPTION_THRESHOLD}: below that, "
                "any two captions on the same topic match."
            )
        if cfg.caption_maybe > cfg.caption_same:
            raise SystemExit("[!] dedup.caption_maybe must be <= dedup.caption_same.")
        cfg.overrides = Path(cfg.overrides)
        return cfg


# --------------------------------------------------------------------------
# signals
# --------------------------------------------------------------------------


def photo_ids(text: str, patterns: list[str]) -> list[str]:
    """Photo codes, uppercased, leading zeros of numbers dropped (AB-09302 = AB-9302)."""
    found: list[str] = []
    for pattern in patterns:
        for m in re.finditer(rf"(?<![A-Z0-9]){pattern}(?![0-9])", text, re.IGNORECASE):
            code = re.sub(r"(?<=-)0+(?=\d)", "", m.group(0).upper())
            if code not in found:
                found.append(code)
    return found


def normalize_caption(text: str, boilerplate: list[str]) -> str:
    """Lowercase words only: no hashtags, mentions, URLs, emoji, punctuation, boilerplate."""
    lines = [
        line
        for line in text.splitlines()
        if not any(re.fullmatch(b, line.strip(), re.IGNORECASE) for b in boilerplate)
    ]
    text = re.sub(r"https?://\S+|www\.\S+", " ", "\n".join(lines))
    text = re.sub(r"[#@]\w+", " ", text)
    return " ".join(re.sub(r"[\W_]+", " ", text.lower()).split())


def similarity(a: str, b: str) -> float:
    """SequenceMatcher ratio of two normalized captions (0-1).

    Pairs sharing few words return their word Dice instead, which is below
    every allowed threshold: the full comparison is the slow part."""
    if not a or not b:
        return 0.0
    ta, tb = set(a.split()), set(b.split())
    dice = 2 * len(ta & tb) / (len(ta) + len(tb))
    # ponytail: heuristic prefilter calibrated on one archive (see MIN_WORD_DICE).
    if dice < MIN_WORD_DICE:
        return dice
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def dhash(path: Path) -> int | None:
    """64-bit difference hash, or None for videos and unreadable images."""
    from PIL import Image, UnidentifiedImageError

    if path.suffix.lower() not in IMAGE_EXT:
        return None
    try:
        with Image.open(path) as img:
            px = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    except (OSError, UnidentifiedImageError):
        return None
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = bits << 1 | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def image_hashes(pubs: list[Publication]) -> list[int | None]:
    try:
        import PIL  # noqa: F401
    except ImportError:
        log("[!] Pillow not installed: image matching skipped (pip install 'creatorvault[dedup]').")
        return [None] * len(pubs)
    return [dhash(p.media[0]) if p.media else None for p in pubs]


YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


def caption_pairs(norms: list[str]) -> Iterator[tuple[int, int]]:
    """Pairs worth comparing: same first year mentioned (e.g. "jul 21 1969"),
    or no year at all on one side. Avoids a full O(n^2) on big archives."""
    buckets: dict[str | None, list[int]] = defaultdict(list)
    for i, norm in enumerate(norms):
        if norm:
            m = YEAR.search(norm)
            buckets[m.group(1) if m else None].append(i)
    loose = buckets.pop(None, [])
    for members in buckets.values():
        yield from combinations(members, 2)
    yield from combinations(loose, 2)
    dated = [i for members in buckets.values() for i in members]
    for i in loose:
        for j in dated:
            yield (min(i, j), max(i, j))


# --------------------------------------------------------------------------
# grouping
# --------------------------------------------------------------------------


class Groups:
    """Union-find that refuses merges between different photo codes or
    across a manual split."""

    def __init__(self, ids: list[list[str]], forbidden: set[frozenset[int]]):
        self.parent = list(range(len(ids)))
        self.ids = [set(x) for x in ids]
        self.members = [{i} for i in range(len(ids))]
        self.forbidden = forbidden

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def same(self, a: int, b: int) -> bool:
        return self.find(a) == self.find(b)

    def union(self, a: int, b: int, force: bool = False) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        if not force:
            if self.ids[ra] and self.ids[rb] and not self.ids[ra] & self.ids[rb]:
                return False
            if self.forbidden and any(
                frozenset((x, y)) in self.forbidden
                for x in self.members[ra]
                for y in self.members[rb]
            ):
                return False
        self.parent[rb] = ra
        self.ids[ra] |= self.ids[rb]
        self.members[ra] |= self.members[rb]
        return True


def pub_ref(p: Publication) -> str:
    """How a publication is named in dedup_overrides.yaml and the reports."""
    return p.permalink or p.draft_id or p.timestamp.isoformat()


def resolve_ref(ref: str, pubs: list[Publication]) -> int | None:
    """Permalink, draft id, or a date/timestamp prefix (2024-06-10, 2024-06-10T16:00)."""
    ref = str(ref)
    hits = [
        i
        for i, p in enumerate(pubs)
        if ref in (p.permalink, p.draft_id) or p.timestamp.isoformat().startswith(ref)
    ]
    if len(hits) != 1:
        log(f"[!] dedup override '{ref}' matches {len(hits)} publications: ignored.")
        return None
    return hits[0]


def load_overrides(path: Path, pubs: list[Publication]) -> tuple[list[list[int]], list[list[int]]]:
    if not path.exists():
        return [], []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, list[list[int]]] = {}
    for kind in ("merge", "split"):
        groups = []
        for group in raw.get(kind) or []:
            resolved = [i for i in (resolve_ref(r, pubs) for r in group) if i is not None]
            if len(resolved) > 1:
                groups.append(resolved)
        out[kind] = groups
    return out["merge"], out["split"]


def dedup(pubs: list[Publication], cfg: DedupConfig) -> tuple[list[Content], list[dict[str, Any]]]:
    """Publications -> Contents (one per distinct content) + borderline pairs."""
    ids = [photo_ids(p.caption, cfg.photo_id_patterns) for p in pubs]
    if not cfg.enabled:
        return [Content([p], photo_ids=i) for p, i in zip(pubs, ids, strict=True)], []

    merges, splits = load_overrides(cfg.overrides, pubs)
    forbidden = {frozenset(pair) for group in splits for pair in combinations(group, 2)}
    groups = Groups(ids, forbidden)
    for group in merges:
        for i in group[1:]:
            groups.union(group[0], i, force=True)

    # 1. Same photo code
    by_code: dict[str, list[int]] = defaultdict(list)
    for i, codes in enumerate(ids):
        for code in codes:
            by_code[code].append(i)
    for members in by_code.values():
        for i in members[1:]:
            groups.union(members[0], i)

    # 2. Same image. ponytail: all-pairs Hamming, fine for a few thousand
    # images; a BK-tree if archives get much bigger.
    hashed = [(i, h) for i, h in enumerate(image_hashes(pubs)) if h is not None]
    for (i, hi), (j, hj) in combinations(hashed, 2):
        if (hi ^ hj).bit_count() <= cfg.image_distance:
            groups.union(i, j)

    # 3. Similar caption
    norms = [normalize_caption(p.caption, cfg.boilerplate) for p in pubs]
    maybe: list[tuple[int, int, float]] = []
    for i, j in caption_pairs(norms):
        if groups.same(i, j):
            continue
        sim = similarity(norms[i], norms[j])
        if sim >= cfg.caption_same:
            groups.union(i, j)
        elif sim >= cfg.caption_maybe:
            maybe.append((i, j, sim))

    members: dict[int, list[int]] = defaultdict(list)
    for i in range(len(pubs)):
        members[groups.find(i)].append(i)
    contents = [
        Content([pubs[i] for i in idx], photo_ids=sorted(groups.ids[root]))
        for root, idx in members.items()
    ]
    contents.sort(key=lambda c: c.first.timestamp)

    review = []
    for i, j, sim in maybe:
        conflict = ids[i] and ids[j] and not set(ids[i]) & set(ids[j])
        if groups.same(i, j) or conflict or frozenset((i, j)) in forbidden:
            continue
        a, b = pubs[i], pubs[j]
        review.append(
            {
                "similarity": f"{sim:.2f}",
                "a_ref": pub_ref(a),
                "a_date": f"{a.timestamp:%Y-%m-%d}",
                "a_caption": a.caption.strip()[:80],
                "b_ref": pub_ref(b),
                "b_date": f"{b.timestamp:%Y-%m-%d}",
                "b_caption": b.caption.strip()[:80],
            }
        )
    groups_n = sum(len(c.publications) > 1 for c in contents)
    log(
        f"[i] Dedup: {len(pubs)} publication(s) -> {len(contents)} content(s), {groups_n} group(s)."
    )
    return contents, review
