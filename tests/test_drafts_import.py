"""`creatorvault import-drafts`: new Meta drafts go into the existing pool."""

from __future__ import annotations

import csv
import json
import re

import pytest
import yaml
from harness import write_config

from creatorvault import cli
from creatorvault.drafts_import import DraftsImportConfig

EXISTING = """---
id: aaaaaaaaaaaa
origin: archive
content_type: posts
format: single
media: [01.jpg]
tags:
  - program/apollo
---

# Jul. 20, 1969: Apollo 11 lands on the Moon

![](01.jpg)

## Description

```text
Jul. 20, 1969: Apollo 11 lands on the Moon. The Eagle has landed in the Sea of Tranquility.
.
#space #history
```
"""

DRAFTS = [
    {  # repeats the post already in the pool (more hashtags, same text)
        "id": "2001",
        "caption": "Jul. 20, 1969: Apollo 11 lands on the Moon. "
        "The Eagle has landed in the Sea of Tranquility.\n.\n#nasa #moon #apollo #a #b #c #d",
        "media": ["2001-01.jpg"],
        "updated": "2025-12-20",
    },
    {  # new, older version of 2003
        "id": "2002",
        "caption": "Sep. 28, 1949: Analog Computing Machine in the Fuel Systems Building.",
        "media": ["2002-01.jpg"],
        "updated": "2025-12-21",
    },
    {  # new, latest version: this one is written
        "id": "2003",
        "caption": "Sep. 28, 1949: Analog Computing Machine in the Fuel Systems Building."
        "\n.\n#nasa #history #science #space #moon #apollo #rocket",
        "media": ["2003-01.jpg", "2003-02.jpg"],
        "updated": "2025-12-22",
    },
    {"id": "2004", "caption": "Pioneer 10 plaque, 1972", "updated": "2025-12-23"},
    {
        "id": "2005",
        "caption": "Nov. 15, 1988: Buran lands on its only flight.",
        "media": ["2005-01.mp4"],
        "updated": "2025-12-24",
        "content_type": "reels",
    },
]


def setup(tmp_path, **section):
    pool_posts, pool_reels = tmp_path / "vault" / "posts", tmp_path / "vault" / "reels"
    (pool_posts / "apollo-11").mkdir(parents=True)
    (pool_posts / "apollo-11" / "post.md").write_text(EXISTING)
    (pool_posts / "apollo-11" / "01.jpg").write_bytes(b"existing")
    pool_reels.mkdir()
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "drafts.json").write_text(json.dumps(DRAFTS))
    for draft in DRAFTS:
        for name in draft.get("media", []):
            (drafts / name).write_bytes(name.encode())
    path = write_config("no_tags", tmp_path)
    cfg = yaml.safe_load(path.read_text())
    cfg["paths"]["meta_drafts"] = str(drafts)
    cfg["drafts_import"] = {"pool_posts": str(pool_posts), "pool_reels": str(pool_reels), **section}
    path.write_text(yaml.safe_dump(cfg))
    return path, pool_posts, pool_reels, drafts


def report(drafts):
    with (drafts / "import-report.csv").open(encoding="utf-8-sig") as fh:
        return {row["draft_id"]: row for row in csv.DictReader(fh)}


def front(text):
    return yaml.safe_load(re.match(r"---\n(.*?)\n---\n", text, re.S)[1])


def test_import_writes_only_new_drafts(tmp_path):
    path, pool_posts, pool_reels, drafts = setup(tmp_path)
    cli.main(["import-drafts", "--config", str(path)])

    assert (pool_posts / "apollo-11" / "post.md").read_text() == EXISTING
    new = pool_posts / "sep-28-1949-analog-computing-machine-in-the-fuel-systems-bui"
    assert sorted(p.name for p in new.iterdir()) == ["01.jpg", "02.jpg", "post.md"]
    assert (new / "01.jpg").read_bytes() == b"2003-01.jpg"
    text = (new / "post.md").read_text()
    fm = front(text)
    assert fm["origin"] == "manual" and fm["format"] == "carousel"
    assert fm["content_type"] == "posts" and len(fm["id"]) == 12
    description = text.split("```text\n")[1].split("\n```")[0]
    assert len(re.findall(r"#\w+", description)) <= 5

    [reel] = list(pool_reels.glob("*/post.md"))
    assert front(reel.read_text())["content_type"] == "reels"
    assert (reel.parent / "01.mp4").exists()

    rows = report(drafts)
    assert rows["2001"]["status"] == "duplicate of pool" and rows["2001"]["detail"] == "apollo-11"
    assert rows["2002"]["status"] == "duplicate draft" and "2003" in rows["2002"]["detail"]
    assert rows["2003"]["status"] == "new" and new.name in rows["2003"]["detail"]
    assert rows["2004"]["status"] == "skipped"
    assert rows["2005"]["status"] == "new"


def test_import_is_idempotent(tmp_path):
    path, pool_posts, pool_reels, drafts = setup(tmp_path)
    cli.main(["import-drafts", "--config", str(path)])
    before = sorted(p.relative_to(tmp_path) for p in (tmp_path / "vault").rglob("*"))
    cli.main(["import-drafts", "--config", str(path)])
    after = sorted(p.relative_to(tmp_path) for p in (tmp_path / "vault").rglob("*"))
    assert before == after
    assert {r["status"] for r in report(drafts).values()} <= {
        "duplicate of pool",
        "duplicate draft",
        "skipped",
    }


def test_dry_run_writes_only_the_report(tmp_path):
    path, pool_posts, pool_reels, drafts = setup(tmp_path, dry_run=True)
    cli.main(["import-drafts", "--config", str(path)])
    assert [p.name for p in pool_posts.iterdir()] == ["apollo-11"]
    assert not list(pool_reels.iterdir())
    assert "would go to posts" in report(drafts)["2003"]["detail"]


def test_missing_reel_pool_leaves_reels_out(tmp_path):
    path, pool_posts, pool_reels, drafts = setup(tmp_path)
    cfg = yaml.safe_load(path.read_text())
    del cfg["drafts_import"]["pool_reels"]
    path.write_text(yaml.safe_dump(cfg))
    cli.main(["import-drafts", "--config", str(path)])
    assert not list(pool_reels.iterdir())
    assert "not written" in report(drafts)["2005"]["detail"]


def test_errors(tmp_path):
    path, pool_posts, _, drafts = setup(tmp_path)
    cfg = yaml.safe_load(path.read_text())
    cfg["drafts_import"] = {}
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(SystemExit, match="pool_posts"):
        cli.main(["import-drafts", "--config", str(path)])
    cfg["drafts_import"] = {"pool_posts": str(tmp_path / "nowhere")}
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(SystemExit, match="Pool folder not found"):
        cli.main(["import-drafts", "--config", str(path)])
    cfg["drafts_import"] = {"pool_posts": str(pool_posts)}
    cfg["paths"]["meta_drafts"] = str(tmp_path / "empty")
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(SystemExit, match="No drafts"):
        cli.main(["import-drafts", "--config", str(path)])
    with pytest.raises(SystemExit, match="Unknown drafts_import"):
        DraftsImportConfig.from_dict({"pool": "x"})
    with pytest.raises(SystemExit, match="must be a mapping"):
        DraftsImportConfig.from_dict(["x"])
