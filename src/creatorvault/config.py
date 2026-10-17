"""Config loading and defaults."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

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
DEFAULT_BATCH_SIZE = 15  # captions sent per Ollama call
DEFAULT_TOLERANCE_MINUTES = 90  # tolerance for the export<->insights join
DEFAULT_INSIGHTS_TZ = "America/Los_Angeles"  # Meta Business Suite exports in Pacific Time
DEFAULT_TIER_SCOPE = "year"  # performance tiers computed year by year
DEFAULT_ONLY_TOP = True  # only write notes for posts in the top tier
DEFAULT_ATTACHMENTS_DIRNAME = "attachments"


def load_config(path: Path) -> dict[str, Any]:
    """Loads config/config.yaml. All script options live here."""
    if not path.exists():
        raise SystemExit(f"[!] Config not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@dataclass
class Settings:
    """config.yaml resolved against the defaults."""

    ig_export: Path
    insights_dir: Path
    out_base: Path
    cache_dir: Path
    taxonomy_path: Path
    tag_model: str
    tag_enabled: bool
    batch_size: int
    tier_metric: str
    tier_top_pct: float
    tolerance_minutes: int
    insights_tz_name: str
    tier_scope: str
    only_top: bool
    attachments_dirname: str


def resolve(cfg: dict[str, Any], cfg_path: Path) -> Settings:
    paths = cfg.get("paths", {})
    tiers_cfg = cfg.get("tiers", {})
    tagging_cfg = cfg.get("tagging", {})
    advanced_cfg = cfg.get("advanced", {})

    try:
        ig_export = Path(paths["ig_export"])
        insights_dir = Path(paths["insights_dir"])
        out_base = Path(paths["out"])
    except KeyError as exc:
        raise SystemExit(f"[!] Missing 'paths.{exc.args[0]}' in {cfg_path}.")

    return Settings(
        ig_export=ig_export,
        insights_dir=insights_dir,
        out_base=out_base,
        # Cache is keyed off the *base* out path (not the timestamped run
        # folder), so the extracted export and the tag cache survive across runs.
        cache_dir=Path(paths.get("cache", out_base / ".ig_archive_cache")),
        taxonomy_path=Path(paths.get("taxonomy", "./config/taxonomy.json")),
        tag_model=tagging_cfg.get("model", DEFAULT_MODEL),
        tag_enabled=bool(tagging_cfg.get("enabled", True)),
        batch_size=int(advanced_cfg.get("batch_size", DEFAULT_BATCH_SIZE)),
        tier_metric=tiers_cfg.get("metric", "engagement"),
        tier_top_pct=float(tiers_cfg.get("top_percentile", 25)),
        tolerance_minutes=int(advanced_cfg.get("tolerance_minutes", DEFAULT_TOLERANCE_MINUTES)),
        insights_tz_name=advanced_cfg.get("insights_tz", DEFAULT_INSIGHTS_TZ),
        tier_scope=advanced_cfg.get("tier_scope", DEFAULT_TIER_SCOPE),
        only_top=bool(advanced_cfg.get("only_top", DEFAULT_ONLY_TOP)),
        attachments_dirname=advanced_cfg.get("attachments_dirname", DEFAULT_ATTACHMENTS_DIRNAME),
    )


def load_timezone(name: str) -> ZoneInfo:
    """A wrong timezone shifts every timestamp and silently breaks the join,
    so an unknown name is a hard error, never a fallback."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise SystemExit(
            f"[!] Unknown timezone '{name}' in advanced.insights_tz.\n"
            "    Use an IANA name such as America/Los_Angeles (Meta's export default)."
        ) from None
