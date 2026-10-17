"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from creatorvault.config import (
    DEFAULT_ATTACHMENTS_DIRNAME,
    DEFAULT_BATCH_SIZE,
    DEFAULT_INSIGHTS_TZ,
    DEFAULT_MODEL,
    DEFAULT_ONLY_TOP,
    DEFAULT_TIER_SCOPE,
    DEFAULT_TOLERANCE_MINUTES,
    load_config,
)
from creatorvault.insights.meta import discover_insight_files, parse_insights
from creatorvault.join import join_posts
from creatorvault.models import log
from creatorvault.sources.instagram import parse_ig_export, prepare_export
from creatorvault.tagging.ollama import tag_posts
from creatorvault.tiers import assign_tiers
from creatorvault.writers.obsidian import write_index, write_notes, write_review

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None  # type: ignore


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Builds an Obsidian archive from your own Instagram posts.",
    )
    ap.add_argument("--config", type=Path, default=Path("config/config.yaml"),
                    help="YAML config file (default: ./config/config.yaml)")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    paths = cfg.get("paths", {})
    tiers_cfg = cfg.get("tiers", {})
    tagging_cfg = cfg.get("tagging", {})
    advanced_cfg = cfg.get("advanced", {})

    try:
        ig_export = Path(paths["ig_export"])
        insights_dir = Path(paths["insights_dir"])
        out_base = Path(paths["out"])
    except KeyError as exc:
        raise SystemExit(f"[!] Missing 'paths.{exc.args[0]}' in {args.config}.")
    # Cache is keyed off the *base* out path (not the timestamped run folder
    # below), so the extracted export and the tag cache survive across runs.
    cache_dir = Path(paths.get("cache", out_base / ".ig_archive_cache"))
    taxonomy_path = Path(paths.get("taxonomy", "./config/taxonomy.json"))

    tag_model = tagging_cfg.get("model", DEFAULT_MODEL)
    tag_enabled = bool(tagging_cfg.get("enabled", True))
    batch_size = int(advanced_cfg.get("batch_size", DEFAULT_BATCH_SIZE))

    tier_metric = tiers_cfg.get("metric", "engagement")
    tier_top_pct = float(tiers_cfg.get("top_percentile", 25))

    tolerance_minutes = int(advanced_cfg.get("tolerance_minutes", DEFAULT_TOLERANCE_MINUTES))
    insights_tz_name = advanced_cfg.get("insights_tz", DEFAULT_INSIGHTS_TZ)
    tier_scope = advanced_cfg.get("tier_scope", DEFAULT_TIER_SCOPE)
    only_top = bool(advanced_cfg.get("only_top", DEFAULT_ONLY_TOP))
    attachments_dirname = advanced_cfg.get("attachments_dirname", DEFAULT_ATTACHMENTS_DIRNAME)

    if not ig_export.exists():
        raise SystemExit(f"[!] Instagram export not found: {ig_export}")
    if not taxonomy_path.exists():
        raise SystemExit(f"[!] Taxonomy not found: {taxonomy_path}")
    insight_files = discover_insight_files(insights_dir)

    if ZoneInfo is None:
        tz = timezone(timedelta(hours=1))
    else:
        try:
            tz = ZoneInfo(insights_tz_name)
        except Exception:  # noqa: BLE001
            log(f"[!] Timezone '{insights_tz_name}' not recognized, using UTC+1.")
            tz = timezone(timedelta(hours=1))

    # Each run gets its own timestamped output folder so a rerun never
    # overwrites a previous archive.
    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = out_base.parent / f"{out_base.name}-{run_stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = cache_dir
    workdir.mkdir(parents=True, exist_ok=True)

    # 1. Instagram export
    root = prepare_export(ig_export, workdir)
    posts = parse_ig_export(root)
    if not posts:
        raise SystemExit("[!] No posts found in the export.")

    # 2. Insights + join
    insights = parse_insights(insight_files, tz)
    review = join_posts(posts, insights, tolerance_minutes)
    assign_tiers(posts, tier_metric, tier_top_pct, tier_scope)

    if only_top:
        posts = [p for p in posts if p.tier in ("top", None)]
        log(f"[i] only_top: {len(posts)} post(s) kept.")

    # 3. Tags
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    if not tag_enabled:
        log("[i] Tagging disabled by config: no semantic tags.")
    else:
        tag_posts(posts, taxonomy, tag_model, batch_size,
                  workdir / "tags_cache.json")

    # 4. Notes
    n = write_notes(posts, out_dir, attachments_dirname, only_top)
    write_index(posts, out_dir, taxonomy)
    write_review(review, out_dir)

    log(f"\n[OK] {n} note(s) written in {out_dir / 'posts'}")
    log(f"     Attachments in {out_dir / attachments_dirname}")
    log(f"     Open '{out_dir}' as a vault in Obsidian and start from 'Post Archive.md'.")
