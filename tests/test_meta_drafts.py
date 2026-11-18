"""Meta drafts: parsing, and how dedup folds them into published content."""

from __future__ import annotations

import json

import pytest
import yaml
from harness import write_config

from creatorvault import cli
from creatorvault.sources.meta_drafts import parse_meta_drafts

# Synthetic drafts: one repeats fixture post p1, two are the same new
# content, one is new and has no image.
DRAFTS = [
    {
        "id": "1001",
        "caption": "Apollo 11 lands on the Moon\nThe Eagle has landed.",
        "media": ["1001.jpg"],
        "updated": "2025-08-01",
        "platforms": ["facebook", "instagram"],
    },
    {
        "id": "1002",
        "caption": "Mercury 7 astronauts pose in their silver pressure suits, 1959. #nasa",
        "media": ["1002.jpg", "missing.jpg"],
        "updated": "2025-08-02",
    },
    {
        "id": "1003",
        "caption": "Mercury 7 astronauts pose in their silver pressure suits, 1959.",
        "updated": "2025-09-01T10:00:00+02:00",
    },
    {"id": "1004", "caption": "Pioneer 10 plaque, 1972", "updated": "2025-08-04"},
    {"caption": "no id: skipped", "updated": "2025-08-05"},
]


def write_drafts(folder, drafts=DRAFTS):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "drafts.json").write_text(json.dumps(drafts))
    for name in ("1001.jpg", "1002.jpg"):
        (folder / name).write_bytes(b"fake")
    return folder


def test_parse(tmp_path, capsys):
    drafts = parse_meta_drafts(write_drafts(tmp_path / "d"))
    assert [d.draft_id for d in drafts] == ["1001", "1002", "1003", "1004"]
    assert drafts[2].timestamp.isoformat() == "2025-09-01T08:00:00+00:00"
    assert [m.name for m in drafts[1].media] == ["1002.jpg"]
    err = capsys.readouterr().err
    assert "missing.jpg not found" in err and "1004 has no image" in err
    assert "without an id" in err
    assert parse_meta_drafts(tmp_path / "nowhere") == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{broken", "Invalid JSON"),
        ('{"id": 1}', "must hold a list"),
        ('[{"id": 1, "updated": "yesterday"}]', "YYYY-MM-DD"),
    ],
)
def test_parse_errors(tmp_path, content, message):
    (tmp_path / "drafts.json").write_text(content)
    with pytest.raises(SystemExit, match=message):
        parse_meta_drafts(tmp_path)


def test_build_with_drafts(tmp_path):
    path = write_config("no_tags", tmp_path)
    cfg = yaml.safe_load(path.read_text())
    cfg["paths"]["meta_drafts"] = str(write_drafts(tmp_path / "drafts"))
    cfg["selection"]["top_percentile"] = 100
    path.write_text(yaml.safe_dump(cfg))
    cli.main(["build", "--config", str(path)])

    vault = tmp_path / "vault"
    review = (vault / "Review.md").read_text().split("## Meta drafts")[1].split("\n## ")[0]
    rows = [line.split("|")[1:-1] for line in review.splitlines() if line.startswith("|")]
    header, body = [h.strip() for h in rows[0]], rows[2:]
    report = {r[0].strip(): dict(zip(header, [c.strip() for c in r], strict=True)) for r in body}
    assert report["1001"]["status"] == "published+draft"
    assert report["1001"]["duplicate_of"] == "https://example.com/p/p1"
    assert report["1003"]["status"] == report["1002"]["status"] == "draft"
    assert report["1003"]["duplicate_of"] == "" and report["1002"]["duplicate_of"] == "1003"
    assert report["1002"]["content"] == report["1003"]["content"]
    assert report["1004"] == {
        "draft_id": "1004",
        "updated": "2025-08-04",
        "content": "2025-08-04-pioneer-10-plaque-1972",
        "status": "draft",
        "duplicate_of": "",
    }

    apollo = (vault / "archive" / "2024-06-10-apollo-11-lands-on-the-moon.md").read_text()
    assert "status: published+draft" in apollo and 'draft_ids: ["1001"]' in apollo
    assert "| Meta draft | `1001` |" in apollo
    mercury = (vault / "archive" / f"{report['1002']['content']}.md").read_text()
    assert 'draft_ids: ["1002", "1003"]' in mercury and "times_published: 0" in mercury
    assert len(list((vault / "archive").glob("*.md"))) == 9 + 2
