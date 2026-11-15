"""`creatorvault queue`: picks the next contents to post and writes their
files (image + ready caption) for Buffer or Business Suite. Publishes nothing."""

from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass, field, fields
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from creatorvault.models import Content, log
from creatorvault.writers.obsidian import IMAGE_EXT, note_stem, slugify

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_days(days: list[str] | str) -> list[str]:
    if isinstance(days, str):
        days = days.split(",")
    days = [d.strip().lower()[:3] for d in days if d.strip()]
    bad = [d for d in days if d not in WEEKDAYS]
    if bad or not days:
        raise SystemExit(f"[!] Queue days must be among {','.join(WEEKDAYS)}, got: {days}")
    return days


def parse_time(value: str) -> str:
    try:
        return datetime.strptime(str(value), "%H:%M").strftime("%H:%M")
    except ValueError:
        raise SystemExit(f"[!] Queue time must be HH:MM, got: {value}") from None


@dataclass
class QueueConfig:
    # Tuesday and Friday are left out: those are reel days.
    days: list[str] = field(default_factory=lambda: ["mon", "wed", "thu", "sat", "sun"])
    time: str = "19:30"
    min_repost_months: int = 12

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> QueueConfig:
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise SystemExit(f"[!] Unknown queue option(s): {', '.join(sorted(unknown))}")
        cfg = cls(**raw)
        cfg.days, cfg.time = parse_days(cfg.days), parse_time(cfg.time)
        return cfg


def slots(start: date, days: list[str], n: int) -> list[date]:
    """The next n dates from start (included) that fall on one of days."""
    wanted = {WEEKDAYS.index(d) for d in days}
    out: list[date] = []
    day = start
    while len(out) < n:
        if day.weekday() in wanted:
            out.append(day)
        day += timedelta(days=1)
    return out


def images(content: Content) -> list[Path]:
    return [m for m in content.media if m.suffix.lower() in IMAGE_EXT]


def pick(
    contents: list[Content], n: int, start: date, min_repost_months: int, axis: str | None
) -> list[Content]:
    """Never-published drafts first (oldest first), then top-tier reposts not
    out for min_repost_months (best first). Avoids two in a row with the same
    value on the primary taxonomy axis when there's a choice."""
    usable = [c for c in contents if images(c)]
    if len(usable) < len(contents):
        log(f"[i] Queue: {len(contents) - len(usable)} content(s) without an image skipped.")
    # ponytail: a month is 30.44 days here; exact calendar months aren't worth a dependency.
    cutoff = start - timedelta(days=round(min_repost_months * 30.44))
    drafts = sorted((c for c in usable if c.status == "draft"), key=lambda c: c.first.timestamp)
    reposts = sorted(
        (
            c
            for c in usable
            if c.published and c.best_tier == "top" and c.published[-1].timestamp.date() <= cutoff
        ),
        key=lambda c: -(c.best_engagement or 0),
    )

    def primary(c: Content) -> str | None:
        values = c.tags.get(axis or "") or []
        return values[0] if values else None

    pool = drafts + reposts
    chosen: list[Content] = []
    last = None
    while pool and len(chosen) < n:
        k = next((i for i, c in enumerate(pool) if last is None or primary(c) != last), 0)
        chosen.append(pool.pop(k))
        last = primary(chosen[-1])
    if len(chosen) < n:
        log(f"[!] Queue: only {len(chosen)} content(s) available for {n} slot(s).")
    return chosen


CSV_FIELDS = ["date", "time", "image", "caption", "note"]


def write_queue(chosen: list[Content], days: list[date], time: str, out: Path) -> Path:
    """NN-YYYY-MM-DD-slug.<ext> + .txt per slot, plus queue.csv. Replaces the
    previous queue's files (and only those) in out."""
    out.mkdir(parents=True, exist_ok=True)
    for old in [*out.glob("[0-9][0-9]-*"), out / "queue.csv"]:
        old.unlink(missing_ok=True)
    rows = []
    for n, (content, day) in enumerate(zip(chosen, days, strict=False), 1):
        stem = f"{n:02d}-{day.isoformat()}-{slugify(content.first.title)}"
        imgs = images(content)
        names = []
        for i, src in enumerate(imgs, 1):
            name = (
                f"{stem}-{i:02d}{src.suffix.lower()}"
                if len(imgs) > 1
                else f"{stem}{src.suffix.lower()}"
            )
            shutil.copy2(src, out / name)
            names.append(name)
        (out / f"{stem}.txt").write_text(content.ready_caption + "\n", encoding="utf-8")
        rows.append(
            {
                "date": day.isoformat(),
                "time": time,
                "image": "|".join(names),
                "caption": content.ready_caption,
                "note": note_stem(content),
            }
        )
    path = out / "queue.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path
