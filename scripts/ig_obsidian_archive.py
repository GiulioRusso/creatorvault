#!/usr/bin/env python3
"""
Deprecated: kept so old instructions keep working for one release.
The code now lives in the creatorvault package; install it with
`pip install -e .` and run `creatorvault` instead.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from creatorvault.cli import main  # noqa: E402

if __name__ == "__main__":
    print("[!] scripts/ig_obsidian_archive.py is deprecated: use `creatorvault`.", file=sys.stderr)
    main()
