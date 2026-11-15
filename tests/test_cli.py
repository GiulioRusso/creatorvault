"""CLI: init, doctor, build errors, shop-catalog dispatch."""

from __future__ import annotations

import json
import os
import shutil
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
        try:
            cli.main(["doctor", "--config", str(path)])
            ok = True
        except SystemExit as exc:
            ok = exc.code == 0
    return ok, capsys.readouterr().out


def dead_host():
    with socket.socket() as s:  # grab a free port, then close it
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}"


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
    ("changes", "status", "check", "message"),
    [
        ({"advanced__insights_tz": "Europe/Atlantis"}, "FAIL", "timezone", "Unknown timezone"),
        ({"paths__ig_export": "/nope.zip"}, "FAIL", "export", "not found"),
        ({"tagging__model": "llama9:404b"}, "WARN", "ollama", "ollama pull llama9:404b"),
        ({"paths__insights_dir": "/nope"}, "WARN", "insights", "archive without metrics"),
        ({"paths__taxonomy": "/nope.json"}, "WARN", "taxonomy", "tagging disabled"),
    ],
)
def test_doctor_bad_configs(tmp_path, capsys, monkeypatch, changes, status, check, message):
    ok, out = run_doctor(edit_config(tmp_path, **changes), capsys, monkeypatch)
    assert ok is (status == "WARN")  # only FAIL makes doctor exit non-zero
    line = next(line for line in out.splitlines() if line.startswith(f"{status}  {check}"))
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
    assert "Invalid taxonomy JSON" in out


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
    dead = dead_host()
    ok, out = run_doctor(write_config("tags", tmp_path), capsys, monkeypatch, host=dead)
    assert ok and "WARN  ollama" in out and "can't reach" in out

    ok, out = run_doctor(
        edit_config(tmp_path, tagging__model="qwen3:235b-cloud"), capsys, monkeypatch
    )
    assert ok and "cloud model" in out

    ok, out = run_doctor(write_config("no_tags", tmp_path), capsys, monkeypatch, host=dead)
    assert ok and "tagging disabled" in out


def test_doctor_missing_config(tmp_path, capsys, monkeypatch):
    ok, out = run_doctor(tmp_path / "missing.yaml", capsys, monkeypatch)
    assert not ok and "FAIL  config" in out


def test_build_rejects_unknown_timezone(tmp_path):
    path = edit_config(tmp_path, advanced__insights_tz="Not/AZone")
    with pytest.raises(SystemExit, match="Unknown timezone 'Not/AZone'"):
        cli.main(["build", "--config", str(path)])


def test_build_missing_export(tmp_path):
    path = edit_config(tmp_path, paths__ig_export="/nope.zip")
    with pytest.raises(SystemExit, match="Instagram export not found"):
        cli.main(["build", "--config", str(path)])


def test_build_broken_taxonomy(tmp_path):
    taxonomy = tmp_path / "taxonomy.json"
    taxonomy.write_text("{broken")
    path = edit_config(tmp_path, paths__taxonomy=str(taxonomy))
    with pytest.raises(SystemExit, match="Invalid taxonomy JSON"):
        cli.main(["build", "--config", str(path)])


def test_build_without_config(tmp_path, monkeypatch, capsys):
    """`creatorvault build export.zip` alone: no config, no insights, no taxonomy,
    Ollama down. Every post still gets a note."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ollama, "OLLAMA_HOST", dead_host())
    cli.main(["build", str(FIXTURES / "instagram-export.zip")])
    notes = list((tmp_path / "vault" / "posts").glob("*.md"))
    assert len(notes) == 9
    assert all("tier: no-data" in n.read_text() for n in notes)
    err = capsys.readouterr().err
    assert "No insights: archive without metrics" in err
    assert "tagging disabled" in err
    assert "notes written" in err


def test_build_finds_newest_export_and_tagging_survives_ollama(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "ig").mkdir(parents=True)
    (tmp_path / "instagram-old.zip").write_bytes(b"not a zip")
    os.utime(tmp_path / "instagram-old.zip", (0, 0))
    shutil.copy(FIXTURES / "instagram-export.zip", tmp_path / "data" / "ig" / "instagram-new.zip")
    (tmp_path / "config").mkdir()
    shutil.copy(FIXTURES / "taxonomy.json", tmp_path / "config" / "taxonomy.json")
    monkeypatch.setattr(ollama, "OLLAMA_HOST", dead_host())
    cli.main(["build", "--out", "out"])
    assert len(list((tmp_path / "out" / "posts").glob("*.md"))) == 9
    assert "Tagging disabled: can't reach" in capsys.readouterr().err


def test_build_no_export_anywhere(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="No Instagram export given"):
        cli.main(["build"])


def test_rebuild_replaces_only_generated_files(tmp_path, monkeypatch):
    cfg = edit_config(tmp_path, run="no_tags")
    cli.main(["build", "--config", str(cfg)])
    vault = tmp_path / "vault"
    mine = vault / "posts" / "my own note.md"
    mine.write_text("hands off")
    stale = vault / "posts" / "2020-01-01-gone.md"
    stale.write_text("generated by an older build")
    manifest = vault / ".creatorvault-manifest.json"
    manifest.write_text(json.dumps([*json.loads(manifest.read_text()), "posts/2020-01-01-gone.md"]))

    cli.main(["build", "--config", str(cfg)])
    assert mine.read_text() == "hands off"
    assert not stale.exists()
    assert not list(tmp_path.glob("vault-*"))


def test_timestamped_out(tmp_path):
    cli.main(["build", "--config", str(edit_config(tmp_path, advanced__timestamped_out=True))])
    (run,) = tmp_path.glob("vault-*")
    assert (run / "Post Archive.md").exists()


def test_shop_catalog_dispatch(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["shop-catalog", "--help"])
    assert exc.value.code == 0
    assert "creatorvault shop-catalog" in capsys.readouterr().out


def test_fixture_export_is_intact():
    assert zipfile.ZipFile(FIXTURES / "instagram-export.zip").testzip() is None
