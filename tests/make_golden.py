#!/usr/bin/env python3
"""
Regenerates tests/golden/ by running the archive builder on the synthetic
fixtures. Only rerun this on purpose, when an output change is intended:

    python tests/make_golden.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from harness import GOLDEN, RUNS, mock_ollama, run_dir, write_config

ENTRY = [sys.executable, "-m", "creatorvault", "build"]


def main() -> None:
    with mock_ollama() as host:
        for run in RUNS:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                cfg = write_config(run, tmp_path)
                env = {**os.environ, "OLLAMA_HOST": host}
                subprocess.run([*ENTRY, "--config", str(cfg)], check=True, env=env)
                dest = GOLDEN / run
                shutil.rmtree(dest, ignore_errors=True)
                shutil.copytree(run_dir(tmp_path), dest)
                print(f"golden/{run} updated")


if __name__ == "__main__":
    main()
