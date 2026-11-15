"""Config loading and defaults."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from creatorvault.dedup import DedupConfig
from creatorvault.hashtags import HashtagConfig
from creatorvault.queue import QueueConfig

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
DEFAULT_ONLY_TOP = False  # true = only write notes for posts in the top tier
DEFAULT_ATTACHMENTS_DIRNAME = "attachments"
DEFAULT_INSIGHTS_DIR = Path("data/insights")
DEFAULT_META_DRAFTS = Path("data/meta-drafts")
DEFAULT_OUT = Path("vault")
DEFAULT_TAXONOMY = Path("config/taxonomy.json")


def load_config(path: Path, required: bool = True) -> dict[str, Any]:
    """Loads config/config.yaml. A missing optional config means all defaults."""
    if not path.exists():
        if required:
            raise SystemExit(f"[!] Config not found: {path}")
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def find_latest_export(data: Path = Path("data"), here: Path = Path(".")) -> Path:
    """The most recently modified instagram-*.zip under ./data/ (any depth) or ./."""
    found = [*data.rglob("instagram-*.zip")] if data.is_dir() else []
    found += here.glob("instagram-*.zip")
    if not found:
        raise SystemExit(
            "[!] No Instagram export given and no instagram-*.zip found in ./data/ or ./.\n"
            "    Run `creatorvault build path/to/export.zip`."
        )
    return max(found, key=lambda p: p.stat().st_mtime)


@dataclass
class Settings:
    """config.yaml resolved against the defaults."""

    ig_export: Path
    insights_dir: Path
    meta_drafts: Path
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
    timestamped_out: bool
    dedup: DedupConfig
    hashtags: HashtagConfig
    queue: QueueConfig


def resolve(cfg: dict[str, Any], export: Path | None = None, out: Path | None = None) -> Settings:
    """config.yaml (possibly empty) + CLI overrides -> Settings.

    Every path is optional: the export falls back to the newest
    instagram-*.zip in ./data/ or ./, the rest to the DEFAULT_* values.
    """
    paths = cfg.get("paths") or {}
    tiers_cfg = cfg.get("tiers") or {}
    tagging_cfg = cfg.get("tagging") or {}
    advanced_cfg = cfg.get("advanced") or {}

    if export is None:
        export = Path(paths["ig_export"]) if paths.get("ig_export") else find_latest_export()
    out_base = out or Path(paths.get("out") or DEFAULT_OUT)

    return Settings(
        ig_export=export,
        insights_dir=Path(paths.get("insights_dir") or DEFAULT_INSIGHTS_DIR),
        meta_drafts=Path(paths.get("meta_drafts") or DEFAULT_META_DRAFTS),
        out_base=out_base,
        # Cache is keyed off the *base* out path (not the timestamped run
        # folder), so the extracted export and the tag cache survive across runs.
        cache_dir=Path(paths.get("cache", out_base / ".ig_archive_cache")),
        taxonomy_path=Path(paths.get("taxonomy") or DEFAULT_TAXONOMY),
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
        timestamped_out=bool(advanced_cfg.get("timestamped_out", False)),
        dedup=DedupConfig.from_dict(cfg.get("dedup") or {}),
        hashtags=HashtagConfig.from_dict(cfg.get("hashtags") or {}),
        queue=QueueConfig.from_dict(cfg.get("queue") or {}),
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
