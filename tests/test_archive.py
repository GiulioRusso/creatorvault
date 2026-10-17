"""Unit tests for parsing, join, tiers and the Obsidian writers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from harness import FIXTURES

from creatorvault.insights.meta import parse_insights, to_float
from creatorvault.join import join_posts
from creatorvault.models import Post
from creatorvault.sources.instagram import fix_mojibake, parse_ig_export, prepare_export
from creatorvault.tiers import assign_tiers
from creatorvault.writers.obsidian import slugify, write_review, yaml_quote

LA = ZoneInfo("America/Los_Angeles")
T0 = datetime(2024, 6, 10, 16, tzinfo=UTC)


def post(key: str, ts: datetime, caption: str = "", **metrics: float) -> Post:
    return Post(key=key, timestamp=ts, caption=caption, metrics=dict(metrics))


def row(ts: datetime, description: str = "", permalink: str | None = None) -> dict:
    return {"publish_time": ts, "permalink": permalink, "description": description, "metrics": {}}


# --- join -----------------------------------------------------------------


@pytest.mark.parametrize(("offset", "matched"), [(89, True), (90, True), (91, False)])
def test_join_tolerance_edges(offset, matched):
    p = post("1", T0)
    review = join_posts([p], [row(T0 + timedelta(minutes=offset), permalink="x")], 90)
    assert (p.permalink == "x") is matched
    assert bool(review) is not matched
    if not matched:
        assert review[0]["issue"] == "no matching post"


def test_join_ambiguous_goes_to_review(tmp_path):
    a, b = post("a", T0), post("b", T0 + timedelta(minutes=30))
    review = join_posts([a, b], [row(T0 + timedelta(minutes=15))], 90)
    assert review[0]["issue"] == "2 posts in the same time window"
    assert a.match_note and b.match_note and not a.metrics
    write_review(review, tmp_path)
    assert "2 posts in the same time window" in (tmp_path / "review.csv").read_text("utf-8-sig")


def test_join_description_disambiguates():
    a = post("a", T0, "Skylab day one launch")
    b = post("b", T0 + timedelta(minutes=30), "Skylab day two crew portrait")
    review = join_posts([a, b], [row(T0, "skylab day two crew portrait", "x")], 90)
    assert review == [] and b.permalink == "x" and a.permalink is None


def test_join_same_post_twice():
    p = post("1", T0)
    review = join_posts([p], [row(T0), row(T0 + timedelta(minutes=5))], 90)
    assert review[0]["issue"] == "post already matched to another row"


# --- insights ---------------------------------------------------------------


def test_insights_dedup_across_overlapping_files():
    csv_file = FIXTURES / "insights" / "2024.csv"
    once = parse_insights([csv_file], LA)
    twice = parse_insights([csv_file, csv_file], LA)
    assert len(once) == len(twice) == 5


def test_insights_xlsx_and_derived_metrics():
    rows = parse_insights([FIXTURES / "insights" / "2025.xlsx"], LA)
    p5 = next(r for r in rows if r["permalink"].endswith("/p5"))
    assert p5["publish_time"] == datetime(2025, 2, 14, 21, tzinfo=UTC)
    assert p5["metrics"]["engagement"] == 800
    assert p5["metrics"]["engagement_rate"] == round(800 / 9000 * 100, 2)


def test_insights_engagement_computed_when_missing():
    rows = parse_insights([FIXTURES / "insights" / "2024.csv"], LA)
    p1 = rows[0]["metrics"]
    assert p1["engagement"] == 900 + 40 + 30 + 120


def test_insights_missing_publish_column(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Reach,Likes\n1,2\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="publish-date column"):
        parse_insights([bad], LA)


@pytest.mark.parametrize(
    ("raw", "value"), [("1.234", 1234.0), ("12,5", 12.5), ("", 0.0), ("n/a", 0.0)]
)
def test_to_float(raw, value):
    assert to_float(raw) == value


# --- tiers ------------------------------------------------------------------


def year_posts() -> list[Post]:
    # 2023 had a much smaller page: raw engagement is low, rate is not.
    return [
        post("a", datetime(2023, 1, 1, tzinfo=UTC), engagement=10, engagement_rate=9.0),
        post("b", datetime(2023, 2, 1, tzinfo=UTC), engagement=5, engagement_rate=2.0),
        post("c", datetime(2024, 1, 1, tzinfo=UTC), engagement=1000, engagement_rate=5.0),
        post("d", datetime(2024, 2, 1, tzinfo=UTC), engagement=500, engagement_rate=1.0),
    ]


def tiers(posts: list[Post]) -> dict[str, str | None]:
    return {p.key: p.tier for p in posts}


def test_tiers_per_year_vs_global():
    per_year, global_ = year_posts(), year_posts()
    assign_tiers(per_year, "engagement", 50, "year")
    assign_tiers(global_, "engagement", 50, "global")
    assert tiers(per_year) == {"a": "top", "b": "average", "c": "top", "d": "average"}
    assert tiers(global_) == {"a": "average", "b": "average", "c": "top", "d": "top"}


def test_tiers_engagement_rate():
    posts = year_posts()
    assign_tiers(posts, "engagement_rate", 25, "global")
    assert tiers(posts) == {"a": "top", "b": "average", "c": "good", "d": "average"}


def test_tiers_missing_metric_is_skipped():
    posts = year_posts()
    assign_tiers(posts, "saves", 25, "global")
    assert set(tiers(posts).values()) == {None}


def test_tiers_no_data_group():
    posts = [*year_posts(), post("e", datetime(2022, 1, 1, tzinfo=UTC))]
    assign_tiers(posts, "engagement", 50, "year")
    assert posts[-1].tier == "no-data"


# --- export -----------------------------------------------------------------


def test_mojibake_roundtrip():
    original = "L'equipaggio è tornato 🚀"
    assert fix_mojibake(original.encode("utf-8").decode("latin-1")) == original
    assert fix_mojibake(original) == original  # already correct
    assert fix_mojibake("") == ""


def test_parse_export_from_zip(tmp_path):
    root = prepare_export(FIXTURES / "instagram-export.zip", tmp_path)
    assert prepare_export(FIXTURES / "instagram-export.zip", tmp_path) == root  # reused
    posts = parse_ig_export(root)
    assert len(posts) == 9
    assert next(p for p in posts if p.key == str(int(T0.timestamp()))).caption.startswith("Apollo")
    assert sum(p.is_carousel for p in posts) == 1
    assert any(p.media[0].suffix == ".mp4" for p in posts)  # found via rglob fallback


def test_prepare_export_rejects_other_files(tmp_path):
    with pytest.raises(SystemExit, match=r"\.zip or a folder"):
        prepare_export(FIXTURES / "taxonomy.json", tmp_path)


def test_post_title():
    assert post("1", T0, "#tag #only\nsecond").title == "Post from 2024-06-10"
    assert post("1", T0, "Hello #world").title == "Hello"


# --- writers ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("Apollo 11 lands!", "apollo-11-lands"),
        ("L'equipaggio è tornato", "lequipaggio-e-tornato"),
        ("🚀🌕", "post"),
        ("", "post"),
        ("a_b  c--d", "a-b-c-d"),
        ("x" * 80, "x" * 60),
    ],
)
def test_slugify(text, slug):
    assert slugify(text) == slug


@pytest.mark.parametrize(
    ("value", "out"),
    [
        (True, "true"),
        (False, "false"),
        (3, "3"),
        (2.5, "2.5"),
        ('say "hi"', '"say \\"hi\\""'),
        ("C:\\path", '"C:\\\\path"'),
        ("key: value", '"key: value"'),
    ],
)
def test_yaml_quote(value, out):
    assert yaml_quote(value) == out


def test_write_review_skips_empty(tmp_path: Path):
    write_review([], tmp_path)
    assert not (tmp_path / "review.csv").exists()
