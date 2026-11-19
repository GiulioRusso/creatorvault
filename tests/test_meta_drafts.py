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


def write_export(path, drafts, files=("2001-01.jpg",), extra=()):
    """A zip like the browser script downloads: flat drafts.json + media."""
    import zipfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("drafts.json", json.dumps(drafts))
        for name in files:
            zf.writestr(name, b"fake")
        for name in extra:
            zf.writestr(name, b"junk")
    return path


EXPORT = [
    {
        "id": "2001",
        "caption": "Feb. 20, 1962: John Glenn before Friendship 7.",
        "media": ["2001-01.jpg"],
        "updated": "2024-12-05T10:00:00",
        "content_type": "posts",
    },
    {"id": "1004", "caption": "Pioneer 10 plaque, 1972 (edited)", "updated": "2025-08-10"},
]


def test_parse_export_zips(tmp_path, capsys):
    folder = write_drafts(tmp_path / "d")
    write_export(
        folder / "meta-drafts-20261119-1000.zip",
        EXPORT,
        extra=("__MACOSX/._2001-01.jpg", ".DS_Store"),
    )
    work = tmp_path / "work"
    drafts = {d.draft_id: d for d in parse_meta_drafts(folder, work)}
    assert sorted(drafts) == ["1001", "1002", "1003", "1004", "2001"]
    # the zip's media are extracted into workdir, junk entries are skipped
    glenn = drafts["2001"].media[0]
    assert glenn.is_file() and work in glenn.parents
    assert not list(work.rglob(".DS_Store")) and not list(work.rglob("__MACOSX"))
    # the same draft in drafts.json and in a zip: the latest `updated` wins
    assert drafts["1004"].caption.endswith("(edited)")
    assert "drafts.json, meta-drafts-20261119-1000.zip" in capsys.readouterr().err


def test_parse_export_zip_without_workdir(tmp_path):
    folder = tmp_path / "d"
    write_export(folder / "meta-drafts-1.zip", EXPORT[:1])
    [draft] = parse_meta_drafts(folder)
    assert draft.media[0].is_file()


@pytest.mark.parametrize(
    ("content", "message"),
    [(b"not a zip", "not a readable ZIP"), (None, "has no drafts.json")],
)
def test_parse_export_zip_errors(tmp_path, content, message):
    import zipfile

    folder = tmp_path / "d"
    folder.mkdir()
    if content is None:
        with zipfile.ZipFile(folder / "other.zip", "w") as zf:
            zf.writestr("photo.jpg", b"fake")
    else:
        (folder / "broken.zip").write_bytes(content)
    with pytest.raises(SystemExit, match=message):
        parse_meta_drafts(folder, tmp_path / "work")


def test_build_with_export_zip(tmp_path):
    path = write_config("no_tags", tmp_path)
    cfg = yaml.safe_load(path.read_text())
    folder = tmp_path / "drafts"
    write_export(folder / "meta-drafts-20261119-1000.zip", EXPORT[:1])
    cfg["paths"]["meta_drafts"] = str(folder)
    cfg["selection"]["top_percentile"] = 100
    path.write_text(yaml.safe_dump(cfg))
    cli.main(["build", "--config", str(path)])

    pool = tmp_path / "vault" / "pool"
    [post] = [p for p in pool.glob("*/post.md") if "John Glenn" in p.read_text()]
    assert (post.parent / "01.jpg").read_bytes() == b"fake"


def test_doctor_counts_export_zips(tmp_path, capsys):
    path = write_config("no_tags", tmp_path)
    cfg = yaml.safe_load(path.read_text())
    folder = write_drafts(tmp_path / "drafts")
    write_export(folder / "meta-drafts-1.zip", EXPORT)
    cfg["paths"]["meta_drafts"] = str(folder)
    path.write_text(yaml.safe_dump(cfg))
    cli.doctor(cli.argparse.Namespace(config=path))
    out = capsys.readouterr().out
    assert "5 draft(s) from drafts.json, meta-drafts-1.zip" in out


def test_drafts_script(capsys):
    cli.main(["drafts-script"])
    script = capsys.readouterr().out
    assert script.startswith("/*") and "draft_posts" in script
    assert "drafts.json" in script and "content_type" in script
