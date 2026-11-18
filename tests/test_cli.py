"""CLI: init, doctor, build errors, catalog dispatch."""

from __future__ import annotations

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
    assert "program" in yaml.safe_load((dest / "config.yaml").read_text())["taxonomy"]
    assert {p.name for p in dest.iterdir()} == {"config.yaml"}
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
    assert out.count("PASS") == 8
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

    ok, out = run_doctor(
        edit_config(
            tmp_path,
            paths__ig_export=str(not_zip),
            paths__insights_dir=str(insights),
        ),
        capsys,
        monkeypatch,
    )
    assert not ok
    assert "not a readable ZIP" in out
    assert "no publish-time column" in out

    ok, out = run_doctor(
        edit_config(tmp_path, paths__ig_export=str(empty_zip)),
        capsys,
        monkeypatch,
    )
    assert "no posts JSON in the ZIP" in out


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
    path = edit_config(tmp_path)
    cfg = yaml.safe_load(path.read_text())
    cfg["taxonomy"] = {"program": "should-be-a-list"}
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(SystemExit, match="taxonomy.program"):
        cli.main(["build", "--config", str(path)])


def test_doctor_without_taxonomy(tmp_path, capsys, monkeypatch):
    path = edit_config(tmp_path)
    cfg = yaml.safe_load(path.read_text())
    cfg.pop("taxonomy")
    path.write_text(yaml.safe_dump(cfg))
    ok, out = run_doctor(path, capsys, monkeypatch)
    assert ok and "WARN  taxonomy" in out and "tagging disabled" in out


def test_build_without_insights_or_ollama(tmp_path, monkeypatch, capsys):
    """No insights, Ollama down: every post still gets a note, unranked."""
    path = edit_config(tmp_path, paths__insights_dir=str(tmp_path / "none"))
    monkeypatch.setattr(ollama, "OLLAMA_HOST", dead_host())
    cli.main(["build", "--config", str(path)])
    notes = list((tmp_path / "vault" / "archive").glob("*.md"))
    assert len(notes) == 9
    assert all("top_percent" not in n.read_text() for n in notes)
    err = capsys.readouterr().err
    assert "No insights: archive without metrics" in err
    assert "Tagging disabled: can't reach" in err
    assert "notes written" in err


def test_config_is_the_only_entrypoint(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="Config not found: config/config.yaml"):
        cli.main(["build"])
    with pytest.raises(SystemExit) as exc:
        cli.main(["build", str(FIXTURES / "instagram-export.zip")])
    assert exc.value.code == 2  # no positional export, no --out: only --config
    path = edit_config(tmp_path)
    cfg = yaml.safe_load(path.read_text())
    del cfg["paths"]["ig_export"]
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(SystemExit, match="paths.ig_export is required"):
        cli.main(["build", "--config", str(path)])


@pytest.mark.parametrize(
    ("cfg", "message"),
    [
        ({"tiers": {"top_percentile": 25}}, "tiers was removed"),
        ({"selection": "all"}, "selection: all|top was removed"),
        ({"advanced": {"only_top": True}}, "advanced.only_top was removed"),
        ({"advanced": {"tier_scope": "year"}}, "advanced.tier_scope was removed"),
        ({"advanced": {"batch": 3}}, "Unknown advanced option"),
        ({"pools": {}}, "Unknown config section"),
        ({"pool": {"enabled": True}}, "pool was removed"),
        ({"advanced": {"attachments_dirname": "a"}}, "attachments_dirname was removed"),
    ],
)
def test_removed_or_unknown_options_fail_clearly(tmp_path, cfg, message):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(SystemExit, match=message):
        cli.main(["build", "--config", str(path)])


def test_rebuild_replaces_only_generated_files(tmp_path, monkeypatch):
    cfg = edit_config(tmp_path, run="no_tags")
    cli.main(["build", "--config", str(cfg)])
    vault = tmp_path / "vault"
    mine = vault / "my own note.md"
    mine.write_text("hands off")
    stale = vault / "archive" / "2020-01-01-gone.md"
    stale.write_text("generated by an older build")

    cli.main(["build", "--config", str(cfg)])
    assert mine.read_text() == "hands off"
    assert not stale.exists()
    assert not list(tmp_path.glob("vault-*"))
    # Notes, pool, Review.md and run.log only: no cache, CSV or database.
    assert {p.name for p in vault.iterdir()} == {
        "archive",
        "pool",
        "Review.md",
        "run.log",
        "my own note.md",
    }
    log = (vault / "run.log").read_text()
    assert "# rerun: cd " in log and f"build --config {cfg}" in log
    assert "[OK] Vault in" in log


def test_timestamped_out(tmp_path):
    cli.main(["build", "--config", str(edit_config(tmp_path, advanced__timestamped_out=True))])
    (run,) = tmp_path.glob("vault-*")
    assert (run / "Review.md").exists()


def test_catalog_reads_its_config_section(tmp_path, monkeypatch):
    from creatorvault import shop_catalog

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"catalog": {"brand": "x"}}))
    with pytest.raises(SystemExit, match="catalog.shop_url is required"):
        cli.main(["catalog", "--config", str(path)])
    path.write_text(yaml.safe_dump({"catalog": {"shop_url": "https://e.com/s", "colour": 1}}))
    with pytest.raises(SystemExit, match="Unknown catalog option"):
        cli.main(["catalog", "--config", str(path)])

    seen = {}
    monkeypatch.setattr(
        shop_catalog, "build_catalog", lambda *a: seen.setdefault("args", a) and [{"id": "1"}]
    )
    monkeypatch.setattr(shop_catalog, "write_catalog_csv", lambda rows, out: seen.update(out=out))
    out = tmp_path / "cat.csv"
    path.write_text(yaml.safe_dump({"catalog": {"shop_url": "https://e.com/s", "out": str(out)}}))
    cli.main(["catalog", "--config", str(path)])
    assert seen == {"args": ("https://e.com/s", "USD", None), "out": out}


def test_fixture_export_is_intact():
    assert zipfile.ZipFile(FIXTURES / "instagram-export.zip").testzip() is None
