#!/usr/bin/env python3
"""
Deprecated: kept so old instructions keep working for one release.
Use `creatorvault shop-catalog` instead (`pip install -e '.[shop]'`).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from creatorvault.shop_catalog import main  # noqa: E402

if __name__ == "__main__":
    print(
        "[!] scripts/shop_to_meta_catalog.py is deprecated: use `creatorvault shop-catalog`.",
        file=sys.stderr,
    )
    main()
