"""Config loading and defaults."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from creatorvault.dedup import DedupConfig
from creatorvault.hashtags import HashtagConfig
from creatorvault.queue import QueueConfig
from creatorvault.review import ReviewConfig
from creatorvault.tagging.taxonomy import normalize_taxonomy

# Model used for tagging, via Ollama (local or cloud). Free.
# Local: any tag pulled with `ollama pull <model>`.
# Cloud (needs `ollama signin`, runs on Ollama's servers): tag with a
# "-cloud" suffix, e.g. "qwen3:235b-cloud", "gpt-oss:120b-cloud".
# Reasoning models (qwen3) are called with thinking off, so they cost no more
# than plain ones: qwen3:8b is a good pick on a 16 GB machine.
DEFAULT_MODEL = "llama3.2:3b"

# Defaults for the `advanced` section of config.yaml. These rarely need
# changing per run (unlike metric/percentile/model), so they're not required
# fields, but they now live in config.yaml instead of only here.
DEFAULT_BATCH_SIZE = 15  # captions sent per Ollama call
DEFAULT_TOLERANCE_MINUTES = 90  # tolerance for the export<->insights join
DEFAULT_INSIGHTS_TZ = "America/Los_Angeles"  # Meta Business Suite exports in Pacific Time
DEFAULT_INSIGHTS_DIR = Path("data/insights")
DEFAULT_META_DRAFTS = Path("data/meta-drafts")
DEFAULT_OUT = Path("vault")

SECTIONS = {
    "paths",
    "content_types",
    "selection",
    "dedup",
    "tagging",
    "review",
    "taxonomy",
    "hashtags",
    "queue",
    "catalog",
    "advanced",
}
ADVANCED = {
    "batch_size",
    "tolerance_minutes",
    "insights_tz",
    "timestamped_out",
}
# Old options that would now be ambiguous: fail with the replacement instead
# of guessing what was meant.
REMOVED = {
    "tiers": "use selection.metric and selection.top_percentile",
    "advanced.only_top": "use selection.top_percentile (100 = every post)",
    "advanced.tier_scope": "use selection.scope",
    "pool": "the pool is always written to <paths.out>/pool",
    "advanced.attachments_dirname": "media live in <paths.out>/pool, next to each post",
}


def load_config(path: Path) -> dict[str, Any]:
    """Loads config/config.yaml: the only place where options are set."""
    if not path.exists():
        raise SystemExit(f"[!] Config not found: {path} (create one with `creatorvault init`).")
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SystemExit(f"[!] Invalid YAML in {path}: {exc}") from None
    if not isinstance(cfg, dict):
        raise SystemExit(f"[!] {path} must contain a YAML mapping.")
    advanced = cfg.get("advanced") or {}
    for key, fix in REMOVED.items():
        section, _, name = key.partition(".")
        if (name in advanced) if name else (section in cfg):
            raise SystemExit(f"[!] {key} was removed: {fix}.")
    if isinstance(cfg.get("selection"), str):
        raise SystemExit(
            "[!] selection: all|top was removed: use selection.top_percentile (100 = every post)."
        )
    bad_advanced = set(advanced) - ADVANCED
    if bad_advanced:
        raise SystemExit(f"[!] Unknown advanced option(s): {', '.join(sorted(bad_advanced))}")
    unknown = set(cfg) - SECTIONS
    if unknown:
        raise SystemExit(f"[!] Unknown config section(s) in {path}: {', '.join(sorted(unknown))}")
    return cfg


@dataclass
class Selection:
    """Which contents get a note: the best top_percentile% on metric, ranked
    per year (scope: year) or over the whole archive (scope: global).
    100 keeps everything, including drafts and posts without metrics."""

    metric: str = "engagement_rate"
    top_percentile: float = 100
    scope: str = "year"

    @classmethod
    def from_dict(cls, raw: Any) -> Selection:
        if not isinstance(raw, dict) or set(raw) - {f.name for f in fields(cls)}:
            raise SystemExit("[!] selection accepts metric, top_percentile and scope.")
        sel = cls(**raw)
        pct = sel.top_percentile
        if type(pct) not in (int, float) or not 0 < pct <= 100:
            raise SystemExit("[!] selection.top_percentile must be a number in (0, 100].")
        if sel.scope not in ("year", "global"):
            raise SystemExit("[!] selection.scope must be 'year' or 'global'.")
        if not isinstance(sel.metric, str) or not sel.metric:
            raise SystemExit("[!] selection.metric must be a metric name.")
        return sel

    @property
    def keeps_all(self) -> bool:
        return self.top_percentile >= 100


@dataclass
class Settings:
    """config.yaml resolved against the defaults."""

    ig_export: Path
    insights_dir: Path
    meta_drafts: Path
    out_base: Path
    cache_dir: Path
    tag_model: str
    tag_enabled: bool
    batch_size: int
    selection: Selection
    tolerance_minutes: int
    insights_tz_name: str
    timestamped_out: bool
    dedup: DedupConfig
    hashtags: HashtagConfig
    queue: QueueConfig
    taxonomy: dict[str, Any] = field(default_factory=dict)
    tag_required: bool = False
    ig_exports: list[Path] = field(default_factory=list)
    content_types: list[str] = field(default_factory=lambda: ["posts"])
    review: ReviewConfig = field(default_factory=ReviewConfig)


def resolve(cfg: dict[str, Any]) -> Settings:
    """config.yaml -> Settings. Only paths.ig_export is required."""
    paths = cfg.get("paths") or {}
    unknown_paths = set(paths) - {
        "ig_export",
        "insights_dir",
        "meta_drafts",
        "out",
        "cache",
    }
    if unknown_paths:
        raise SystemExit(f"[!] Unknown paths option(s): {', '.join(sorted(unknown_paths))}")
    tagging_cfg = cfg.get("tagging") or {}
    advanced_cfg = cfg.get("advanced") or {}
    content_types = cfg.get("content_types", ["posts"])
    if (
        not isinstance(content_types, list)
        or not content_types
        or any(kind not in ("posts", "reels") for kind in content_types)
    ):
        raise SystemExit("[!] content_types must be a non-empty list of posts and/or reels.")
    taxonomy = normalize_taxonomy(cfg["taxonomy"]) if "taxonomy" in cfg else {}

    exports = paths.get("ig_export")
    if not exports:
        raise SystemExit("[!] paths.ig_export is required: the Instagram export ZIP(s).")
    if isinstance(exports, (str, Path)):
        exports = [exports]
    if not isinstance(exports, list) or any(not isinstance(p, (str, Path)) for p in exports):
        raise SystemExit("[!] paths.ig_export must be a path or a list of export paths.")
    exports = [Path(p) for p in exports]
    if len(exports) > 1 and any(p.suffix.lower() != ".zip" or p.is_dir() for p in exports):
        raise SystemExit("[!] Multiple Instagram exports must be ZIP files.")
    out_base = Path(paths.get("out") or DEFAULT_OUT)
    cache_dir = Path(paths.get("cache") or out_base.parent / ".creatorvault-cache")
    if cache_dir.resolve().is_relative_to(out_base.resolve()):
        raise SystemExit("[!] paths.cache must be outside paths.out: the vault holds notes only.")

    return Settings(
        ig_export=exports[0],
        insights_dir=Path(paths.get("insights_dir") or DEFAULT_INSIGHTS_DIR),
        meta_drafts=Path(paths.get("meta_drafts") or DEFAULT_META_DRAFTS),
        out_base=out_base,
        # Model answers only (tags, review decisions), outside the vault and
        # shared by every config in the folder, so reruns don't re-ask the model.
        cache_dir=cache_dir,
        tag_model=tagging_cfg.get("model", DEFAULT_MODEL),
        tag_enabled=bool(tagging_cfg.get("enabled", True)),
        batch_size=int(advanced_cfg.get("batch_size", DEFAULT_BATCH_SIZE)),
        selection=Selection.from_dict(cfg.get("selection") or {}),
        tolerance_minutes=int(advanced_cfg.get("tolerance_minutes", DEFAULT_TOLERANCE_MINUTES)),
        insights_tz_name=advanced_cfg.get("insights_tz", DEFAULT_INSIGHTS_TZ),
        timestamped_out=bool(advanced_cfg.get("timestamped_out", False)),
        dedup=DedupConfig.from_dict(cfg.get("dedup") or {}),
        hashtags=HashtagConfig.from_dict(cfg.get("hashtags") or {}),
        queue=QueueConfig.from_dict(cfg.get("queue") or {}),
        taxonomy=taxonomy,
        tag_required=bool(tagging_cfg.get("required", False)),
        ig_exports=exports,
        content_types=list(dict.fromkeys(content_types)),
        review=ReviewConfig.from_dict(
            cfg.get("review") or {}, tagging_cfg.get("model", DEFAULT_MODEL)
        ),
    )


@dataclass
class CatalogConfig:
    """`catalog:` section: shop listing page -> Meta Commerce Manager CSV."""

    shop_url: str
    out: Path = Path("meta_catalog.csv")
    brand: str | None = None  # default: last path segment of shop_url
    currency: str = "USD"

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> CatalogConfig:
        raw = cfg.get("catalog")
        if not isinstance(raw, dict) or not raw.get("shop_url"):
            raise SystemExit("[!] catalog.shop_url is required to build the shop catalog.")
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise SystemExit(f"[!] Unknown catalog option(s): {', '.join(sorted(unknown))}")
        out = cls(**raw)
        out.out = Path(out.out)
        return out


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
