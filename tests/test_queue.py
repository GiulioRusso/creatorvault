"""`creatorvault queue`: slots, selection order, files written."""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import yaml
from harness import write_config
from test_meta_drafts import write_drafts

from creatorvault import cli
from creatorvault.hashtags import HASHTAG
from creatorvault.models import META_DRAFT, Content, Publication
from creatorvault.queue import QueueConfig, parse_days, parse_time, pick, slots


def test_slots_skip_excluded_days():
    # 2026-11-30 is a Monday; Tuesday and Friday are reel days.
    got = slots(date(2026, 11, 30), ["mon", "wed", "thu", "sat", "sun"], 6)
    assert [d.isoformat() for d in got] == [
        "2026-11-30",
        "2026-12-02",
        "2026-12-03",
        "2026-12-05",
        "2026-12-06",
        "2026-12-07",
    ]


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: parse_days("mon,funday"), "Queue days"),
        (lambda: parse_days(""), "Queue days"),
        (lambda: parse_time("7pm"), "HH:MM"),
        (lambda: QueueConfig.from_dict({"dayz": []}), "Unknown queue option"),
    ],
)
def test_bad_queue_options(call, message):
    with pytest.raises(SystemExit, match=message):
        call()


def test_queue_config_normalizes():
    cfg = QueueConfig.from_dict({"days": "Monday, sat", "time": "9:05"})
    assert cfg.days == ["mon", "sat"] and cfg.time == "09:05"


def content(n: int, program: str | None, *, draft=False, rank=10, year=2024, media="x.jpg"):
    p = Publication(
        key=str(n),
        timestamp=datetime(year, 1, n, tzinfo=UTC),
        caption=f"Post {n}",
        media=[Path(media)] if media else [],
        top_percent=None if draft else rank,
        metrics={} if draft else {"engagement": 100 - n},
        source=META_DRAFT if draft else "instagram_export",
        draft_id=str(n) if draft else None,
    )
    return Content([p], tags={"program": [program]} if program else {})


def test_pick_order_and_axis_alternation(capsys):
    contents = [
        content(1, "apollo", rank=5),  # best rank
        content(2, "apollo"),
        content(3, "gemini"),
        content(4, "apollo", draft=True, year=2025),
        content(5, "apollo", draft=True, year=2023),
        content(6, "skylab", rank=None),  # no metrics: never a repost
        content(7, "voyager", year=2026),  # top but posted too recently
        content(8, None, draft=True, media="clip.mp4"),  # no image
    ]
    chosen = pick(contents, 10, date(2026, 6, 1), 12, "program")
    assert [c.first.key for c in chosen] == ["5", "3", "4", "1", "2"]
    err = capsys.readouterr().err
    assert "1 content(s) without an image" in err and "only 5 content(s)" in err


def test_queue_command(tmp_path):
    path = write_config("no_tags", tmp_path)
    cfg = yaml.safe_load(path.read_text())
    cfg["paths"]["meta_drafts"] = str(write_drafts(tmp_path / "drafts"))
    cfg["hashtags"] = {"strategy": "keep_original", "max": 5}
    cfg["selection"]["top_percentile"] = 100
    out = tmp_path / "queue"
    cfg["queue"] = {"next": 6, "days": "mon,thu", "start": "2026-11-30", "out": str(out)}
    path.write_text(yaml.safe_dump(cfg))
    out.mkdir()
    (out / "99-stale.txt").write_text("old queue")
    (out / "mine.txt").write_text("not ours")

    cli.main(["queue", "--config", str(path)])
    with open(out / "queue.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert [r["date"] for r in rows] == [
        "2026-11-30",
        "2026-12-03",
        "2026-12-07",
        "2026-12-10",
        "2026-12-14",
        "2026-12-17",
    ]
    assert len({r["note"] for r in rows}) == len(rows)  # no content twice
    assert all(len(HASHTAG.findall(r["caption"])) <= 5 for r in rows)
    assert rows[0]["note"].startswith("2025-08-02-mercury-7")  # the never-published draft
    assert all(r["time"] == "19:30" for r in rows)
    assert all((out / name).exists() for r in rows for name in r["image"].split("|"))
    assert any("|" in r["image"] for r in rows)  # carousel: every image copied
    texts = sorted(out.glob("0*.txt"))
    assert [t.read_text().strip() for t in texts] == [r["caption"] for r in rows]
    assert not (out / "99-stale.txt").exists() and (out / "mine.txt").exists()


@pytest.mark.parametrize(
    ("raw", "message"), [({"start": "soon"}, "queue.start must be"), ({"next": 0}, "queue.next")]
)
def test_queue_bad_options(raw, message):
    with pytest.raises(SystemExit, match=message):
        QueueConfig.from_dict(raw)
