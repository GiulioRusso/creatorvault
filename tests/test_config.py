"""Single-file configuration: category lists, selection, removed options."""

import argparse
import zipfile

import pytest
import yaml
from harness import FIXTURES, TAXONOMY, mock_ollama

from creatorvault import cli
from creatorvault.config import load_config, resolve
from creatorvault.tagging import ollama
from creatorvault.tagging.taxonomy import normalize_taxonomy, response_schema


def test_inline_categories_build_images_captions_and_tags(tmp_path, monkeypatch):
    taxonomy = TAXONOMY
    cfg = {
        "paths": {
            "ig_export": str(FIXTURES / "instagram-export.zip"),
            "insights_dir": str(tmp_path / "no-insights"),
            "meta_drafts": str(tmp_path / "no-drafts"),
            "out": str(tmp_path / "vault"),
        },
        "dedup": {"enabled": False},
        "tagging": {"model": "mock-model:1b", "required": True},
        "taxonomy": {k: v["values"] for k, v in taxonomy.items() if not k.startswith("_")},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    with mock_ollama() as host:
        monkeypatch.setattr(ollama, "OLLAMA_HOST", host)
        cli.main(["build", "--config", str(path)])
        assert cli.doctor(argparse.Namespace(config=path))
    notes = list((tmp_path / "vault" / "archive").glob("*.md"))
    assert len(notes) == 9
    assert list((tmp_path / "vault" / "pool").glob("*/01.*"))
    assert all("## Description" in n.read_text() for n in notes)
    assert any("  - program/" in n.read_text() for n in notes)


EXPORT = {"paths": {"ig_export": "export.zip"}}


def test_selection_is_one_percentile():
    assert resolve(EXPORT).selection.keeps_all
    sel = resolve({**EXPORT, "selection": {"top_percentile": 25, "scope": "global"}}).selection
    assert (sel.top_percentile, sel.scope, sel.keeps_all) == (25, "global", False)
    for bad in ({"top_percentile": 0}, {"top_percentile": 101}, {"top_percentile": True}):
        with pytest.raises(SystemExit, match="top_percentile"):
            resolve({**EXPORT, "selection": bad})
    with pytest.raises(SystemExit, match="scope"):
        resolve({**EXPORT, "selection": {"scope": "month"}})
    with pytest.raises(SystemExit, match="selection accepts"):
        resolve({**EXPORT, "selection": {"top": 25}})


def test_top_percentile_keeps_only_ranked_contents(tmp_path):
    path = tmp_path / "config.yaml"
    cfg = {
        "paths": {
            "ig_export": str(FIXTURES / "instagram-export.zip"),
            "insights_dir": str(FIXTURES / "insights"),
            "meta_drafts": str(tmp_path / "none"),
            "out": str(tmp_path / "vault"),
        },
        "tagging": {"enabled": False},
    }
    counts = {}
    for pct in (100, 50, 20):
        cfg["selection"] = {"metric": "engagement", "top_percentile": pct, "scope": "global"}
        path.write_text(yaml.safe_dump(cfg))
        cli.main(["build", "--config", str(path)])
        notes = list((tmp_path / "vault" / "archive").glob("*.md"))
        counts[pct] = len(notes)
        if pct < 100:
            pcts = [int(n.read_text().split("top_percent: ")[1].split()[0]) for n in notes]
            assert all(v <= pct for v in pcts)
    assert counts[100] == 9 and counts[100] > counts[50] > counts[20] > 0


def test_separate_taxonomy_path_is_no_longer_supported():
    with pytest.raises(SystemExit, match="Unknown paths option.*taxonomy"):
        resolve({"paths": {"ig_export": "x.zip", "taxonomy": "old-categories.json"}})


def test_categories_support_simple_and_detailed_forms():
    taxonomy = normalize_taxonomy(
        {"program": ["apollo", "gemini", "apollo"], "angle": {"values": ["photo"], "multi": False}}
    )
    assert taxonomy["program"] == {"values": ["apollo", "gemini"], "multi": True}
    fields = response_schema(taxonomy)["properties"]["posts"]["items"]["properties"]
    assert "maxItems" not in fields["program"]
    assert fields["angle"]["maxItems"] == 1


@pytest.mark.parametrize(
    "raw", [None, [], {}, {"program": []}, {"program": "apollo"}, {"program": [5]}]
)
def test_invalid_inline_categories_fail_clearly(raw):
    with pytest.raises(SystemExit, match="[Tt]axonomy"):
        normalize_taxonomy(raw)


def test_bad_yaml_fails_clearly(tmp_path):
    path = tmp_path / "config.yaml"
    for text in ("paths: [", "- not-a-mapping"):
        path.write_text(text)
        with pytest.raises(SystemExit, match=str(path)):
            load_config(path)


def test_required_tagging_and_cache_changes(tmp_path, monkeypatch):
    settings = resolve({**EXPORT, "tagging": {"required": True}})

    def unavailable(_model):
        raise SystemExit("model unavailable")

    monkeypatch.setattr(ollama, "check_model", unavailable)
    with pytest.raises(SystemExit, match="Tagging is required"):
        cli.tag([], {"program": {"values": ["apollo"]}}, settings)
    with pytest.raises(SystemExit, match="model unavailable"):
        cli.check_ollama(settings)
    with pytest.raises(SystemExit, match="add taxonomy"):
        cli.tag([], {}, settings)
    monkeypatch.setattr(ollama, "check_model", lambda _: "OK")
    settings.cache_dir = tmp_path
    caches = []
    monkeypatch.setattr(ollama, "tag_posts", lambda *args: caches.append(args[-1]))
    for taxonomy in ({"program": {"values": ["apollo"]}}, {"program": {"values": ["gemini"]}}):
        cli.tag([], taxonomy, settings)
    assert caches[0] != caches[1]
    settings.tag_model = "another-model"
    cli.tag([], taxonomy, settings)
    assert caches[2] != caches[1]


def test_doctor_nested_export_ignores_viewing_history(tmp_path):
    path = tmp_path / "export.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("account/ads_information/posts_viewed.json", "{}")
        archive.writestr("account/your_instagram_activity/media/posts_1.json", "[]")
    settings = resolve({"paths": {"ig_export": str(path)}})
    assert cli.check_export(settings).endswith("your_instagram_activity/media/posts_1.json")
