"""Repost detection. All captions and images are synthetic."""

from __future__ import annotations

import builtins
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from harness import NASA_PATTERNS

from creatorvault import cli, dedup
from creatorvault.dedup import (
    DEFAULT_BOILERPLATE,
    DedupConfig,
    caption_pairs,
    normalize_caption,
    photo_ids,
)
from creatorvault.models import Publication
from creatorvault.writers.obsidian import write_notes

Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")


def pub(n: int, caption: str, media: list[Path] | None = None, year: int = 2024) -> Publication:
    return Publication(
        key=str(n),
        timestamp=datetime(year, 1 + n % 12, 1 + n, 18, tzinfo=UTC),
        caption=caption,
        media=media or [],
        permalink=f"https://example.com/p/{n}",
    )


def cfg(tmp_path: Path, **kw) -> DedupConfig:
    kw.setdefault("photo_id_patterns", NASA_PATTERNS)
    return DedupConfig(overrides=tmp_path / "overrides.yaml", **kw)


def groups(contents) -> list[list[str]]:
    return sorted(sorted(p.key for p in c.publications) for c in contents)


# --- signals ----------------------------------------------------------------


def test_photo_ids_normalized():
    text = "as14-66-09302, AS14-66-9302, S69-12345_G01-S, xAS11-40-5903, ISS030-E-12345, GT4-1-2"
    assert photo_ids(text, NASA_PATTERNS) == [
        "AS14-66-9302",
        "S69-12345_G01-S",
        "GT4-1-2",
        "ISS030-E-12345",
    ]


def test_normalize_caption():
    raw = "Jul. 21, 1969 — Moonwalk! 🚀 @nasa https://x.y/z\n.\n.\nCheck the link in bio!\n#apollo"
    assert normalize_caption(raw, DEFAULT_BOILERPLATE) == "jul 21 1969 moonwalk"


def test_caption_pairs_bucketed_by_year():
    norms = ["a 1969", "b 1969", "c 1972", "no year", "", "other no year"]
    pairs = set(caption_pairs(norms))
    assert (0, 1) in pairs and (0, 2) not in pairs and (1, 2) not in pairs
    assert {(0, 3), (2, 3), (3, 5)} <= pairs
    assert not any(4 in p for p in pairs)


def test_unknown_option():
    with pytest.raises(SystemExit, match="Unknown dedup option"):
        DedupConfig.from_dict({"caption_sme": 0.9})
    assert DedupConfig.from_dict({"overrides": "x.yaml"}).overrides == Path("x.yaml")


# --- acceptance -------------------------------------------------------------


def test_same_photo_code_different_captions(tmp_path):
    pubs = [
        pub(1, "Earthrise, Dec. 24, 1968. AS08-14-2383"),
        pub(2, "The most famous photo of the Earth ever taken (AS08-14-02383) #apollo8"),
        pub(3, "Throwback: Bill Anders' shot from lunar orbit. Code: as08-14-2383", year=2025),
    ]
    contents, review = dedup.dedup(pubs, cfg(tmp_path))
    assert groups(contents) == [["1", "2", "3"]] and review == []
    (content,) = contents
    assert content.photo_ids == ["AS08-14-2383"] and content.first.key == "1"

    write_notes(contents, tmp_path / "vault", {c.id: "slug" for c in contents})
    (note,) = (tmp_path / "vault" / "archive").glob("*.md")
    text = note.read_text()
    assert note.name.startswith("2024-02-02-")  # first publication names the note
    assert "times_published: 3" in text and "  - repost/yes" in text
    assert 'photo_ids: ["AS08-14-2383"]' in text
    assert text.count("| Instagram |") == 3


def make_image(path: Path, seed: int, quality: int = 95, size: int = 256) -> Path:
    """Coloured blocks: enough structure for a dHash, different per seed."""
    img = Image.new("RGB", (256, 256))
    draw = ImageDraw.Draw(img)
    for i in range(8):
        v = (seed * 37 * i) % 256
        x, y = i * 32, (i * seed * 19) % 200
        draw.rectangle([x, y, x + 60, y + 50], fill=(v, 255 - v, (v * 3) % 256))
    img.resize((size, size)).save(path, quality=quality)
    return path


def test_same_image_rewritten_caption(tmp_path):
    a = make_image(tmp_path / "a.jpg", 7)
    b = make_image(tmp_path / "b.jpg", 7, quality=40, size=180)  # re-encoded, smaller
    c = make_image(tmp_path / "c.png", 2)
    pubs = [
        pub(1, "Crew portrait before launch.", [a]),
        pub(2, "Totally new words for this one", [b]),
        pub(3, "Skylab crew portraits at the pad, 1973", [c]),
        pub(4, "A reel", [tmp_path / "v.mp4"]),
    ]
    contents, _ = dedup.dedup(pubs, cfg(tmp_path))
    assert groups(contents) == [["1", "2"], ["3"], ["4"]]


def test_different_codes_never_merge(tmp_path):
    text = "Jul. 20, 1969: Buzz Aldrin deploys the seismometer at Tranquility Base. {}"
    pubs = [pub(1, text.format("AS11-40-5948")), pub(2, text.format("AS11-40-5949"))]
    contents, review = dedup.dedup(pubs, cfg(tmp_path))
    assert len(contents) == 2 and review == []


def test_borderline_pair_is_a_candidate_not_a_merge(tmp_path):
    pubs = [
        # Rewritten from scratch: too different for captions alone (code/image catch these).
        pub(1, "Gemini 4 spacewalk over the Pacific, June 1965. Ed White floats outside."),
        pub(2, "Ed White during the first American spacewalk, Gemini 4, June 1965, Pacific."),
        # Reworded: borderline (0.73), left to the local model.
        pub(3, "Saturn V rolls out to pad 39A in 1967, ahead of Apollo 4."),
        pub(4, "In 1967 the Saturn V rolled out to pad 39A ahead of the Apollo 4 flight."),
        # Lightly edited repost: merged (0.90).
        pub(5, "Skylab rides a Saturn V to orbit, May 14, 1973."),
        pub(6, "Skylab rides a Saturn V into orbit, May 14, 1973!"),
    ]
    contents, review = dedup.dedup(pubs, cfg(tmp_path))
    assert groups(contents) == [["1"], ["2"], ["3"], ["4"], ["5", "6"]]
    (row,) = review
    assert 0.70 <= float(row["similarity"]) < 0.85
    assert {row["a_ref"], row["b_ref"]} == {"https://example.com/p/3", "https://example.com/p/4"}


def test_similarity_ignores_shared_topic_words():
    a = normalize_caption("Jul. 20, 1969: interior view of the Apollo 11 Lunar Module.", [])
    b = normalize_caption("Jul. 20, 1969: Aldrin deploys the Apollo 11 seismic experiment.", [])
    assert dedup.similarity(a, b) < 0.70
    with pytest.raises(SystemExit, match="caption_maybe must be >= 0.6"):
        DedupConfig.from_dict({"caption_maybe": 0.5})


def test_overrides_merge_and_split(tmp_path, capsys):
    pubs = [
        pub(1, "Saturn V rolls out to pad 39A in 1967, ahead of Apollo 4."),
        pub(2, "In 1967 the Saturn V rolled out to pad 39A ahead of the Apollo 4 flight."),
        pub(3, "Voyager golden record"),
        pub(4, "Pioneer plaque"),
    ]
    c = cfg(tmp_path)
    c.overrides.write_text(
        yaml.safe_dump(
            {
                "merge": [["https://example.com/p/3", pubs[3].timestamp.date().isoformat()]],
                "split": [["https://example.com/p/1", "https://example.com/p/2", "nope"]],
            }
        )
    )
    contents, review = dedup.dedup(pubs, c)
    assert groups(contents) == [["1"], ["2"], ["3", "4"]] and review == []
    assert "'nope' matches 0 publications" in capsys.readouterr().err


def test_disabled_keeps_one_content_per_publication(tmp_path):
    pubs = [pub(1, "AS08-14-2383"), pub(2, "AS08-14-2383")]
    contents, _ = dedup.dedup(pubs, cfg(tmp_path, enabled=False))
    assert groups(contents) == [["1"], ["2"]] and contents[0].photo_ids == ["AS08-14-2383"]


def test_without_pillow(tmp_path, monkeypatch, capsys):
    real_import = builtins.__import__

    def no_pil(name, *args, **kwargs):
        if name == "PIL":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pil)
    a = make_image(tmp_path / "a.jpg", 7)
    contents, _ = dedup.dedup([pub(1, "x", [a]), pub(2, "y", [a])], cfg(tmp_path))
    assert len(contents) == 2
    assert "Pillow not installed" in capsys.readouterr().err


def test_build_leaves_nothing_to_review(tmp_path):
    from harness import write_config

    path = write_config("tags", tmp_path)
    data = yaml.safe_load(path.read_text())
    # The lowest threshold allowed: any borderline pair found stays separate.
    # Without a local reviewer it simply stays two contents.
    data["dedup"] = {"caption_maybe": 0.6, "overrides": str(tmp_path / "none.yaml")}
    data["tagging"]["enabled"] = False
    path.write_text(yaml.safe_dump(data))
    cli.main(["build", "--config", str(path)])
    vault = tmp_path / "vault"
    assert not list(vault.glob("*review*.csv"))
    notes = [n.read_text() for n in (vault / "archive").glob("*.md")]
    assert len(notes) == 9 and not any("Needs review" in n for n in notes)
