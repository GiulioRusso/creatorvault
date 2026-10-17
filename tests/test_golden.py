"""The archive builder must reproduce tests/golden/ byte for byte."""

from __future__ import annotations

import pytest
from harness import GOLDEN, RUNS, mock_ollama, run_dir, snapshot, write_config

from creatorvault import cli
from creatorvault.tagging import ollama


@pytest.mark.parametrize("run", RUNS)
def test_golden(run, tmp_path, monkeypatch):
    cfg = write_config(run, tmp_path)
    with mock_ollama() as host:
        monkeypatch.setattr(ollama, "OLLAMA_HOST", host)
        cli.main(["--config", str(cfg)])
    assert snapshot(run_dir(tmp_path)) == snapshot(GOLDEN / run)
