"""Config loading and defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    raise SystemExit(
        "[!] Missing pyyaml: activate the venv and run `pip install -r requirements.txt`."
    )

# Model used for tagging, via Ollama (local or cloud). Free.
# Local: any tag pulled with `ollama pull <model>`.
# Cloud (needs `ollama signin`, runs on Ollama's servers): tag with a
# "-cloud" suffix, e.g. "qwen3:235b-cloud", "gpt-oss:120b-cloud".
# Prefer non-reasoning models (llama3.2, mistral) over reasoning ones (qwen3,
# deepseek-r1): reasoning models burn hundreds of hidden "thinking" tokens
# per call before answering, which is pure latency for a bulk classification
# task like this and can blow past the request timeout.
DEFAULT_MODEL = "llama3.2:3b"

# Defaults for the `advanced` section of config.yaml. These rarely need
# changing per run (unlike metric/percentile/model), so they're not required
# fields, but they now live in config.yaml instead of only here.
DEFAULT_BATCH_SIZE = 15          # captions sent per Ollama call
DEFAULT_TOLERANCE_MINUTES = 90   # tolerance for the export<->insights join
DEFAULT_INSIGHTS_TZ = "America/Los_Angeles"  # Meta Business Suite exports in Pacific Time
DEFAULT_TIER_SCOPE = "year"      # performance tiers computed year by year
DEFAULT_ONLY_TOP = True          # only write notes for posts in the top tier
DEFAULT_ATTACHMENTS_DIRNAME = "attachments"


def load_config(path: Path) -> dict[str, Any]:
    """Loads config/config.yaml. All script options live here."""
    if not path.exists():
        raise SystemExit(f"[!] Config not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
