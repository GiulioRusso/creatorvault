"""Unit tests for parsing, join, ranking and the Obsidian writers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from harness import FIXTURES

from creatorvault.insights.meta import parse_insights, to_float
from creatorvault.join import join_posts
from creatorvault.models import Post
from creatorvault.ranking import assign_ranks
from creatorvault.sources.instagram import fix_mojibake, parse_ig_export, prepare_export
from creatorvault.writers.obsidian import slugify, yaml_quote

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


def test_join_ambiguous_is_returned_unassigned():
    a, b = post("a", T0), post("b", T0 + timedelta(minutes=30))
    review = join_posts([a, b], [row(T0 + timedelta(minutes=15))], 90)
    assert review[0]["issue"] == "2 posts in the same time window"
    assert not a.metrics and not b.metrics


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


# --- ranking ----------------------------------------------------------------


def year_posts() -> list[Post]:
    # 2023 had a much smaller page: raw engagement is low, rate is not.
    return [
        post("a", datetime(2023, 1, 1, tzinfo=UTC), engagement=10, engagement_rate=9.0),
        post("b", datetime(2023, 2, 1, tzinfo=UTC), engagement=5, engagement_rate=2.0),
        post("c", datetime(2024, 1, 1, tzinfo=UTC), engagement=1000, engagement_rate=5.0),
        post("d", datetime(2024, 2, 1, tzinfo=UTC), engagement=500, engagement_rate=1.0),
    ]


def ranks(posts: list[Post]) -> dict[str, int | None]:
    return {p.key: p.top_percent for p in posts}


def test_ranks_per_year_vs_global():
    per_year, global_ = year_posts(), year_posts()
    assign_ranks(per_year, "engagement", "year")
    assign_ranks(global_, "engagement", "global")
    assert ranks(per_year) == {"a": 50, "b": 100, "c": 50, "d": 100}
    assert ranks(global_) == {"a": 75, "b": 100, "c": 25, "d": 50}


def test_ranks_engagement_rate_ties_and_zero():
    posts = year_posts()
    assign_ranks(posts, "engagement_rate", "global")
    assert ranks(posts) == {"a": 25, "b": 75, "c": 50, "d": 100}
    tied = [post(k, T0, engagement=v) for k, v in (("x", 3), ("y", 3), ("z", 0))]
    assign_ranks(tied, "engagement")
    assert ranks(tied) == {"x": 34, "y": 34, "z": 100}  # a zero is a value, not missing


def test_ranks_missing_metric(capsys):
    posts = [*year_posts(), post("e", datetime(2022, 1, 1, tzinfo=UTC))]
    assign_ranks(posts, "engagement")
    assert posts[-1].top_percent is None
    assign_ranks(posts, "saves")
    assert set(ranks(posts).values()) == {None}
    assert "No post has the metric 'saves'" in capsys.readouterr().err


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
        prepare_export(FIXTURES / "config.yaml", tmp_path)


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
