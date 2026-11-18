"""Post/reel selection through parsing, insight matching and vault output."""

import json
import zipfile
from datetime import UTC, datetime

import pytest
import yaml

from creatorvault import cli
from creatorvault.config import resolve
from creatorvault.dedup import DedupConfig, dedup
from creatorvault.join import join_posts
from creatorvault.models import Content, Publication
from creatorvault.sources.instagram import parse_ig_export
from creatorvault.sources.meta_drafts import parse_meta_drafts
from creatorvault.writers.obsidian import write_notes


def entry(title, uri):
    return {"media": [{"uri": uri, "title": title, "creation_timestamp": 1704110400}]}


def export_zip(path, *, posts=True, reels=True, wrapped=True):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("logged_information/past_instagram_insights/reels.json", "{}")
        if posts:
            archive.writestr(
                "content/posts_1.json", json.dumps([entry("Synthetic photo", "media/a.jpg")])
            )
            archive.writestr("media/a.jpg", b"synthetic photo")
        if reels:
            raw = [entry("Synthetic reel", "media/a.mp4")]
            archive.writestr(
                "content/reels.json", json.dumps({"ig_reels_media": raw} if wrapped else raw)
            )
            archive.writestr("media/a.mp4", b"synthetic reel")


@pytest.mark.parametrize(
    "selected,count", [(["posts"], 1), (["reels"], 1), (["posts", "reels"], 2)]
)
def test_build_selects_kinds_and_matches_same_time_correctly(tmp_path, selected, count):
    export = tmp_path / "export.zip"
    export_zip(export)
    insights = tmp_path / "insights"
    insights.mkdir()
    (insights / "metrics.csv").write_text(
        "Publish time,Post type,Description,Reach,Likes\n"
        "2024-01-01 12:00,IG image,Synthetic photo,100,10\n"
        "2024-01-01 12:00,IG reel,Synthetic reel,200,20\n"
    )
    config = {
        "paths": {
            "ig_export": str(export),
            "insights_dir": str(insights),
            "out": str(tmp_path / "vault"),
            "meta_drafts": str(tmp_path / "no-drafts"),
        },
        "content_types": selected,
        "dedup": {"enabled": False},
        "tagging": {"enabled": False},
        "advanced": {"insights_tz": "UTC"},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    cli.main(["build", "--config", str(path)])
    vault = tmp_path / "vault"
    notes = list((vault / "archive").glob("*.md"))
    assert len(notes) == count
    assert not (vault / "review.csv").exists()
    if "reels" in selected:
        note = next(n.read_text() for n in notes if "# Synthetic reel" in n.read_text())
        assert "content_types: [reels]" in note and "  - reel\n" in note
        assert "reach: 200" in note
        assert list((vault / "pool").glob("*/01.mp4"))
    if "posts" in selected:
        note = next(n.read_text() for n in notes if "# Synthetic photo" in n.read_text())
        assert "reach: 100" in note


@pytest.mark.parametrize("wrapped", [True, False])
def test_reel_only_metadata_passes_doctor(tmp_path, wrapped):
    path = tmp_path / "reels.zip"
    export_zip(path, posts=False, wrapped=wrapped)
    settings = resolve({"content_types": ["reels"], "paths": {"ig_export": str(path)}})
    assert "reels.json" in cli.check_export(settings)
    with pytest.raises(SystemExit, match="no posts JSON"):
        cli.check_export(resolve({"paths": {"ig_export": str(path)}}))
    root = tmp_path / "extracted"
    with zipfile.ZipFile(path) as archive:
        archive.extractall(root)
    (reel,) = parse_ig_export(root, content_types=["reels"])
    assert reel.content_type == "reels" and reel.key.startswith("reel-")
    assert "content/reels.json" in cli.check_export(settings)


@pytest.mark.parametrize("value", [[], "posts", ["stories"], [None]])
def test_invalid_content_selection(value):
    with pytest.raises(SystemExit, match="content_types"):
        resolve({"content_types": value, "paths": {"ig_export": "test.zip"}})


def test_kind_mismatch_does_not_assign_metrics():
    post = Publication("1", datetime(2024, 1, 1, tzinfo=UTC), "caption")
    review = join_posts(
        [post],
        [
            {
                "publish_time": post.timestamp,
                "content_type": "reels",
                "permalink": "",
                "description": "caption",
                "metrics": {"reach": 99},
            }
        ],
        90,
    )
    assert not post.metrics and review[0]["issue"] == "no matching post"


def test_post_and_reel_with_same_caption_do_not_overwrite(tmp_path):
    stamp = datetime(2024, 1, 1, tzinfo=UTC)
    post = Publication("1", stamp, "Same caption")
    reel = Publication("reel-1", stamp, "Same caption", content_type="reels")
    contents = [Content([post]), Content([reel])]
    write_notes(contents, tmp_path, {c.id: c.id for c in contents})
    names = {p.name for p in (tmp_path / "archive").glob("*.md")}
    assert names == {"2024-01-01-same-caption.md", "2024-01-01-reel-same-caption.md"}


def test_reel_draft_type_is_explicit(tmp_path):
    path = tmp_path / "drafts.json"
    path.write_text(json.dumps([{"id": "1", "updated": "2024-01-01", "content_type": "reels"}]))
    assert parse_meta_drafts(tmp_path)[0].content_type == "reels"
    path.write_text(json.dumps([{"id": "1", "updated": "2024-01-01", "content_type": "unknown"}]))
    with pytest.raises(SystemExit, match="content_type"):
        parse_meta_drafts(tmp_path)


def test_auto_merge_threshold_is_configurable(tmp_path):
    texts = [
        "Saturn V rolls out to pad 39A in 1967, ahead of Apollo 4.",
        "In 1967 the Saturn V rolled out to pad 39A ahead of the Apollo 4 flight.",
    ]
    pubs = [
        Publication(str(n), datetime(2024, 1, n + 1, tzinfo=UTC), text)
        for n, text in enumerate(texts)
    ]
    common = {"overrides": str(tmp_path / "none.yaml")}
    contents, review = dedup(pubs, DedupConfig.from_dict(common))
    assert len(contents) == 2 and len(review) == 1
    contents, review = dedup(pubs, DedupConfig.from_dict({**common, "caption_same": 0.7}))
    assert len(contents) == 1 and review == []


@pytest.mark.parametrize(
    "options",
    [
        {"caption_same": 75},
        {"caption_maybe": -1},
        {"caption_same": "75%"},
        {"caption_same": float("nan")},
        {"caption_maybe": 0.9, "caption_same": 0.75},
    ],
)
def test_invalid_match_thresholds(options):
    with pytest.raises(SystemExit, match="dedup"):
        DedupConfig.from_dict(options)
