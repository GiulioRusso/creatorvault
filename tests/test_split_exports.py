"""Synthetic split downloads: multiple Instagram ZIP parts."""

import argparse
import json
import zipfile

import pytest
import yaml

from creatorvault import cli
from creatorvault.config import resolve
from creatorvault.sources.instagram import parse_ig_export


def entry(n, uri):
    return {
        "creation_timestamp": 1704067200 + n * 86400,
        "title": f"Synthetic content {n}",
        "media": [{"uri": uri}],
    }


def test_ambiguous_basename_does_not_choose_wrong_photo(tmp_path):
    export = tmp_path / "part1"
    export.mkdir()
    (export / "posts_1.json").write_text(json.dumps([entry(1, "missing/image.jpg")]))
    for folder in ("one", "two"):
        target = export / folder
        target.mkdir()
        (target / "image.jpg").write_text(folder)
    with pytest.raises(SystemExit, match="Ambiguous media"):
        parse_ig_export(export)


def test_every_numbered_json_is_imported(tmp_path):
    for n in (1, 2):
        (tmp_path / f"photo{n}.jpg").write_bytes(b"synthetic")
        (tmp_path / f"posts_{n}.json").write_text(json.dumps([entry(n, f"photo{n}.jpg")]))
    assert len(parse_ig_export(tmp_path)) == 2


@pytest.mark.parametrize("metadata", ["repeated", "separate", "media-only"])
def test_build_from_two_zip_parts(tmp_path, metadata):
    first = tmp_path / "part1.zip"
    second = tmp_path / "part2.zip"
    records = [entry(1, "media/one/photo.jpg"), entry(2, "media/two/photo.jpg")]
    with zipfile.ZipFile(first, "w") as archive:
        archive.writestr("account/media/one/photo.jpg", b"first photo")
        archive.writestr(
            "account/content/posts_1.json",
            json.dumps(records if metadata != "separate" else records[:1]),
        )
    with zipfile.ZipFile(second, "w") as archive:
        archive.writestr("account/media/two/photo.jpg", b"second photo")
        if metadata != "media-only":
            archive.writestr(
                "account/content/posts_1.json",
                json.dumps(records if metadata == "repeated" else records[1:]),
            )
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "paths": {
                    "ig_export": [str(first), str(second)],
                    "insights_dir": str(tmp_path / "no-insights"),
                    "meta_drafts": str(tmp_path / "no-drafts"),
                    "out": str(tmp_path / "vault"),
                },
                "dedup": {"enabled": False},
                "tagging": {"enabled": False},
            }
        )
    )
    cli.main(["build", "--config", str(config)])
    assert len(list((tmp_path / "vault" / "archive").glob("*.md"))) == 2
    images = list((tmp_path / "vault" / "pool").glob("*/*.jpg"))
    assert {p.read_bytes() for p in images} == {b"first photo", b"second photo"}
    assert cli.doctor(argparse.Namespace(config=config))


@pytest.mark.parametrize("paths", [{"ig_export": [2]}, {"unknown": "value"}])
def test_invalid_split_config(paths):
    with pytest.raises(SystemExit, match="paths"):
        resolve({"paths": {"ig_export": "export.zip", **paths}})


def test_multiple_exports_must_be_zip_files():
    with pytest.raises(SystemExit, match="ZIP files"):
        resolve({"paths": {"ig_export": ["part1.zip", "extracted-folder"]}})
