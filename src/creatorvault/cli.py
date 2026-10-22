"""Command-line entry point: init, doctor, build, shop-catalog."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import datetime
from importlib.resources import files
from pathlib import Path

from creatorvault.config import Settings, load_config, load_timezone, resolve
from creatorvault.insights.meta import (
    discover_insight_files,
    load_table,
    map_columns,
    parse_insights,
)
from creatorvault.join import join_posts
from creatorvault.models import log
from creatorvault.sources.instagram import (
    POSTS_JSON_CANDIDATES,
    find_posts_json,
    parse_ig_export,
    prepare_export,
)
from creatorvault.tagging import ollama
from creatorvault.tagging.taxonomy import axis_names, axis_values
from creatorvault.tiers import assign_tiers
from creatorvault.writers.obsidian import write_index, write_notes, write_review

DEFAULT_CONFIG = Path("config/config.yaml")
TEMPLATES = {"config.yaml": "config.yaml", "taxonomy.json": "taxonomy.json"}


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------


def init(dest: Path) -> None:
    """Copies the config and taxonomy templates into dest. Never overwrites."""
    targets = {dest / name: src for name, src in TEMPLATES.items()}
    existing = [str(p) for p in targets if p.exists()]
    if existing:
        raise SystemExit(f"[!] Refusing to overwrite: {', '.join(existing)}")
    dest.mkdir(parents=True, exist_ok=True)
    for target, src in targets.items():
        target.write_text(
            (files("creatorvault") / "templates" / src).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        log(f"[OK] Wrote {target}")
    log("     Fill in your paths, then run `creatorvault doctor`.")


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------


def build(s: Settings) -> None:
    if not s.ig_export.exists():
        raise SystemExit(f"[!] Instagram export not found: {s.ig_export}")
    if not s.taxonomy_path.exists():
        raise SystemExit(f"[!] Taxonomy not found: {s.taxonomy_path}")
    insight_files = discover_insight_files(s.insights_dir)
    tz = load_timezone(s.insights_tz_name)

    # Each run gets its own timestamped output folder so a rerun never
    # overwrites a previous archive.
    run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = s.out_base.parent / f"{s.out_base.name}-{run_stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = s.cache_dir
    workdir.mkdir(parents=True, exist_ok=True)

    # 1. Instagram export
    root = prepare_export(s.ig_export, workdir)
    posts = parse_ig_export(root)
    if not posts:
        raise SystemExit("[!] No posts found in the export.")

    # 2. Insights + join
    insights = parse_insights(insight_files, tz)
    review = join_posts(posts, insights, s.tolerance_minutes)
    assign_tiers(posts, s.tier_metric, s.tier_top_pct, s.tier_scope)

    if s.only_top:
        posts = [p for p in posts if p.tier in ("top", None)]
        log(f"[i] only_top: {len(posts)} post(s) kept.")

    # 3. Tags
    taxonomy = json.loads(s.taxonomy_path.read_text(encoding="utf-8"))
    if not s.tag_enabled:
        log("[i] Tagging disabled by config: no semantic tags.")
    else:
        ollama.tag_posts(posts, taxonomy, s.tag_model, s.batch_size, workdir / "tags_cache.json")

    # 4. Notes
    n = write_notes(posts, out_dir, s.attachments_dirname, s.only_top)
    write_index(posts, out_dir, taxonomy)
    write_review(review, out_dir)

    log(f"\n[OK] {n} note(s) written in {out_dir / 'posts'}")
    log(f"     Attachments in {out_dir / s.attachments_dirname}")
    log(f"     Open '{out_dir}' as a vault in Obsidian and start from 'Post Archive.md'.")


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------


def check_export(s: Settings) -> str:
    if not s.ig_export.exists():
        raise SystemExit(f"not found: {s.ig_export}")
    if s.ig_export.is_dir():
        return f"posts JSON: {find_posts_json(s.ig_export).relative_to(s.ig_export)}"
    try:
        with zipfile.ZipFile(s.ig_export) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        raise SystemExit(f"not a readable ZIP: {s.ig_export}") from None
    for rel in POSTS_JSON_CANDIDATES:
        if rel in names:
            return f"posts JSON: {rel}"
    found = sorted(n for n in names if Path(n).name.startswith("posts_") and n.endswith(".json"))
    if found:
        return f"posts JSON: {found[0]}"
    raise SystemExit("no posts JSON in the ZIP (did you pick JSON, not HTML?)")


def check_insights(s: Settings) -> str:
    paths = discover_insight_files(s.insights_dir)
    for path in paths:
        header, _rows = load_table(path)
        if "publish_time" not in map_columns(header):
            raise SystemExit(f"{path.name}: no publish-time column in {header}")
    return f"{len(paths)} file(s), publish-time column found"


def check_timezone(s: Settings) -> str:
    load_timezone(s.insights_tz_name)
    return s.insights_tz_name


def check_taxonomy(s: Settings) -> str:
    if not s.taxonomy_path.exists():
        raise SystemExit(f"not found: {s.taxonomy_path}")
    try:
        taxonomy = json.loads(s.taxonomy_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON ({exc})") from None
    axes = axis_names(taxonomy)
    if not axes:
        raise SystemExit("no axes (keys not starting with _)")
    empty = [a for a in axes if not isinstance(taxonomy[a], dict) or not axis_values(taxonomy[a])]
    if empty:
        raise SystemExit(f"axes without values: {', '.join(empty)}")
    return f"{len(axes)} axis/axes: {', '.join(axes)}"


def check_ollama(s: Settings) -> str:
    if not s.tag_enabled:
        return "tagging disabled, skipped"
    try:
        with urllib.request.urlopen(f"{ollama.OLLAMA_HOST}/api/tags", timeout=5) as resp:
            models = {m["name"] for m in json.loads(resp.read()).get("models", [])}
    except OSError as exc:
        raise SystemExit(f"can't reach {ollama.OLLAMA_HOST} ({exc}): run `ollama serve`") from None
    if s.tag_model.endswith("-cloud"):
        return f"reachable; cloud model {s.tag_model} (needs `ollama signin`)"
    if s.tag_model not in models and f"{s.tag_model}:latest" not in models:
        raise SystemExit(f"model {s.tag_model} not pulled: run `ollama pull {s.tag_model}`")
    return f"reachable, {s.tag_model} pulled"


CHECKS: list[tuple[str, Callable[[Settings], str]]] = [
    ("export", check_export),
    ("insights", check_insights),
    ("timezone", check_timezone),
    ("taxonomy", check_taxonomy),
    ("ollama", check_ollama),
]


def doctor(cfg_path: Path) -> bool:
    """Prints a pass/fail table; returns True when every check passes."""
    results: list[tuple[str, bool, str]] = []
    try:
        s = resolve(load_config(cfg_path), cfg_path)
        results.append(("config", True, str(cfg_path)))
    except SystemExit as exc:
        results.append(("config", False, str(exc)))
    else:
        for name, check in CHECKS:
            try:
                results.append((name, True, check(s)))
            except SystemExit as exc:
                results.append((name, False, str(exc)))
    for name, ok, detail in results:
        detail = detail.removeprefix("[!] ").replace("\n", " ")
        print(f"{'PASS' if ok else 'FAIL'}  {name:<9} {detail}")
    return all(ok for _, ok, _ in results)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    # shop-catalog has its own parser (and optional dependencies).
    if argv[:1] == ["shop-catalog"]:
        from creatorvault.shop_catalog import main as shop_main

        shop_main(argv[1:])
        return

    ap = argparse.ArgumentParser(
        prog="creatorvault",
        description="Turn your own social-media exports into a searchable Obsidian archive.",
    )
    sub = ap.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="copy the config and taxonomy templates into ./config/")
    p_init.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_CONFIG.parent,
        help="destination folder (default: ./config)",
    )
    for name, help_ in (
        ("build", "build the Obsidian archive"),
        ("doctor", "check config, exports, timezone, taxonomy and Ollama"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument(
            "--config",
            type=Path,
            default=DEFAULT_CONFIG,
            help="YAML config file (default: ./config/config.yaml)",
        )
    sub.add_parser("shop-catalog", help="shop listing page -> Meta catalog CSV (see --help)")
    args = ap.parse_args(argv)

    if args.command == "init":
        init(args.dir)
    elif args.command == "doctor":
        if not doctor(args.config):
            raise SystemExit(1)
    else:
        build(resolve(load_config(args.config), args.config))
