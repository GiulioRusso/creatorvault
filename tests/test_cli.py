"""CLI: init, doctor, build errors, shop-catalog dispatch."""

from __future__ import annotations

import json
import socket
import zipfile

import pytest
import yaml
from harness import FIXTURES, mock_ollama, write_config

from creatorvault import cli
from creatorvault.tagging import ollama


def test_init_copies_templates_and_refuses_overwrite(tmp_path):
    dest = tmp_path / "config"
    cli.main(["init", "--dir", str(dest)])
    assert yaml.safe_load((dest / "config.yaml").read_text())["paths"]
    assert "example_axis" in json.loads((dest / "taxonomy.json").read_text())
    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        cli.main(["init", "--dir", str(dest)])


def edit_config(tmp_path, run="tags", **changes):
    """Fixture config with dotted-key overrides, e.g. advanced__insights_tz=..."""
    path = write_config(run, tmp_path)
    cfg = yaml.safe_load(path.read_text())
    for key, value in changes.items():
        section, name = key.split("__")
        cfg.setdefault(section, {})[name] = value
    path.write_text(yaml.safe_dump(cfg))
    return path


def run_doctor(path, capsys, monkeypatch, host=None):
    with mock_ollama() as mock_host:
        monkeypatch.setattr(ollama, "OLLAMA_HOST", host or mock_host)
        ok = cli.doctor(path)
    return ok, capsys.readouterr().out


def test_doctor_good_config(tmp_path, capsys, monkeypatch):
    ok, out = run_doctor(write_config("tags", tmp_path), capsys, monkeypatch)
    assert ok, out
    assert out.count("PASS") == 6
    assert "posts JSON: your_instagram_activity/content/posts_1.json" in out


def test_doctor_cli_exit_code(tmp_path, monkeypatch, capsys):
    path = edit_config(tmp_path, advanced__insights_tz="Mars/Olympus_Mons")
    with mock_ollama() as host:
        monkeypatch.setattr(ollama, "OLLAMA_HOST", host)
        with pytest.raises(SystemExit) as exc:
            cli.main(["doctor", "--config", str(path)])
    assert exc.value.code == 1
    assert "FAIL  timezone" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("changes", "failing", "message"),
    [
        ({"advanced__insights_tz": "Europe/Atlantis"}, "timezone", "Unknown timezone"),
        ({"tagging__model": "llama9:404b"}, "ollama", "ollama pull llama9:404b"),
        ({"paths__ig_export": "/nope.zip"}, "export", "not found"),
        ({"paths__insights_dir": "/nope"}, "insights", "Insights folder not found"),
        ({"paths__taxonomy": "/nope.json"}, "taxonomy", "not found"),
    ],
)
def test_doctor_bad_configs(tmp_path, capsys, monkeypatch, changes, failing, message):
    ok, out = run_doctor(edit_config(tmp_path, **changes), capsys, monkeypatch)
    assert not ok
    line = next(line for line in out.splitlines() if line.startswith(f"FAIL  {failing}"))
    assert message in line


def test_doctor_bad_files(tmp_path, capsys, monkeypatch):
    not_zip = tmp_path / "export.zip"
    not_zip.write_text("nope")
    empty_zip = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty_zip, "w") as zf:
        zf.writestr("readme.txt", "html export")
    insights = tmp_path / "insights"
    insights.mkdir()
    (insights / "2024.csv").write_text("Reach,Likes\n1,2\n")
    taxonomy = tmp_path / "taxonomy.json"
    taxonomy.write_text('{"_note": "", "empty": {"values": []}}')

    ok, out = run_doctor(
        edit_config(
            tmp_path,
            paths__ig_export=str(not_zip),
            paths__insights_dir=str(insights),
            paths__taxonomy=str(taxonomy),
        ),
        capsys,
        monkeypatch,
    )
    assert not ok
    assert "not a readable ZIP" in out
    assert "no publish-time column" in out
    assert "axes without values: empty" in out

    taxonomy.write_text("{broken")
    ok, out = run_doctor(
        edit_config(tmp_path, paths__ig_export=str(empty_zip), paths__taxonomy=str(taxonomy)),
        capsys,
        monkeypatch,
    )
    assert "no posts JSON in the ZIP" in out
    assert "invalid JSON" in out


def test_doctor_export_folder_and_posts_fallback(tmp_path, capsys, monkeypatch):
    export = tmp_path / "export"
    (export / "odd").mkdir(parents=True)
    (export / "odd" / "posts_2.json").write_text("[]")
    zipped = tmp_path / "odd.zip"
    with zipfile.ZipFile(zipped, "w") as zf:
        zf.writestr("odd/posts_2.json", "[]")
    for path in (export, zipped):
        ok, out = run_doctor(edit_config(tmp_path, paths__ig_export=str(path)), capsys, monkeypatch)
        assert ok and "odd/posts_2.json" in out


def test_doctor_ollama_unreachable_and_skips(tmp_path, capsys, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{s.getsockname()[1]}"
    ok, out = run_doctor(write_config("tags", tmp_path), capsys, monkeypatch, host=dead)
    assert not ok and "can't reach" in out

    ok, out = run_doctor(
        edit_config(tmp_path, tagging__model="qwen3:235b-cloud"), capsys, monkeypatch
    )
    assert ok and "cloud model" in out

    ok, out = run_doctor(write_config("no_tags", tmp_path), capsys, monkeypatch, host=dead)
    assert ok and "tagging disabled" in out


def test_doctor_missing_config(tmp_path, capsys):
    assert not cli.doctor(tmp_path / "missing.yaml")
    assert "FAIL  config" in capsys.readouterr().out


def test_build_rejects_unknown_timezone(tmp_path):
    path = edit_config(tmp_path, advanced__insights_tz="Not/AZone")
    with pytest.raises(SystemExit, match="Unknown timezone 'Not/AZone'"):
        cli.main(["build", "--config", str(path)])


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"paths__ig_export": "/nope.zip"}, "Instagram export not found"),
        ({"paths__taxonomy": "/nope.json"}, "Taxonomy not found"),
    ],
)
def test_build_missing_inputs(tmp_path, changes, message):
    with pytest.raises(SystemExit, match=message):
        cli.main(["build", "--config", str(edit_config(tmp_path, **changes))])


def test_build_missing_path_key(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"paths": {"ig_export": "x"}}))
    with pytest.raises(SystemExit, match="Missing 'paths.insights_dir'"):
        cli.main(["build", "--config", str(path)])


def test_shop_catalog_dispatch(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["shop-catalog", "--help"])
    assert exc.value.code == 0
    assert "creatorvault shop-catalog" in capsys.readouterr().out


def test_fixture_export_is_intact():
    assert zipfile.ZipFile(FIXTURES / "instagram-export.zip").testzip() is None
