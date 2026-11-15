"""Command-line entry point: init, doctor, build, shop-catalog."""

from __future__ import annotations

import argparse
import json
import sys
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
from creatorvault.writers.obsidian import sync_manifest, write_index, write_notes, write_review

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


def load_taxonomy(s: Settings) -> dict:
    """Missing taxonomy = no tagging (warning). A broken one is a hard error."""
    if not s.taxonomy_path.exists():
        return {}
    try:
        return json.loads(s.taxonomy_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[!] Invalid taxonomy JSON in {s.taxonomy_path} ({exc})") from None


def tag(posts: list, taxonomy: dict, s: Settings) -> None:
    """Tags in place. Ollama down or model missing = warning, never an error."""
    if not s.tag_enabled:
        log("[i] Tagging disabled by config: no semantic tags.")
        return
    if not taxonomy:
        log(f"[!] No taxonomy at {s.taxonomy_path}: tagging disabled (`creatorvault init`).")
        return
    try:
        ollama.check_model(s.tag_model)
        ollama.tag_posts(
            posts, taxonomy, s.tag_model, s.batch_size, s.cache_dir / "tags_cache.json"
        )
    except SystemExit as exc:
        log(f"[!] Tagging disabled: {str(exc).removeprefix('[!] ')}")


def print_summary(rows: list[tuple[str, int]]) -> None:
    width = max(len(label) for label, _ in rows)
    log("")
    for label, value in rows:
        log(f"  {label:<{width}}  {value:>6}")


def build(s: Settings) -> None:
    if not s.ig_export.exists():
        raise SystemExit(f"[!] Instagram export not found: {s.ig_export}")
    insight_files = discover_insight_files(s.insights_dir)
    tz = load_timezone(s.insights_tz_name)
    taxonomy = load_taxonomy(s)

    out_dir = s.out_base
    if s.timestamped_out:
        # Each run gets its own folder, so a rerun never touches a previous archive.
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = s.out_base.parent / f"{s.out_base.name}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    workdir = s.cache_dir
    workdir.mkdir(parents=True, exist_ok=True)

    # 1. Instagram export
    root = prepare_export(s.ig_export, workdir)
    posts = parse_ig_export(root)
    if not posts:
        raise SystemExit("[!] No posts found in the export.")
    n_read = len(posts)

    # 2. Insights + join
    if not insight_files:
        log("[i] No insights: archive without metrics.")
    insights = parse_insights(insight_files, tz)
    review = join_posts(posts, insights, s.tolerance_minutes)
    assign_tiers(posts, s.tier_metric, s.tier_top_pct, s.tier_scope)
    if not insight_files:
        for p in posts:
            p.tier = "no-data"

    if s.only_top:
        posts = [p for p in posts if p.tier in ("top", None)]
        log(f"[i] only_top: {len(posts)} post(s) kept.")

    # 3. Tags
    tag(posts, taxonomy, s)

    # 4. Notes
    written = write_notes(posts, out_dir, s.attachments_dirname)
    written.append(write_index(posts, out_dir, taxonomy))
    written += write_review(review, out_dir)
    sync_manifest(out_dir, written)

    print_summary(
        [
            ("posts read", n_read),
            ("unique contents", n_read),
            ("duplicate groups", 0),
            ("drafts", 0),
            ("notes written", len(posts)),
            ("rows to review", len(review)),
        ]
    )
    log(f"\n[OK] Vault in {out_dir}: open it in Obsidian and start from 'Post Archive.md'.")


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------


class Warn(Exception):
    """A doctor check that found something degraded but not blocking."""


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
    if not paths:
        raise Warn(f"no insights in {s.insights_dir}: archive without metrics")
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
        raise Warn(f"not found: {s.taxonomy_path}: tagging disabled")
    taxonomy = load_taxonomy(s)
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
        return ollama.check_model(s.tag_model)
    except SystemExit as exc:
        raise Warn(f"{exc}; tagging will be skipped") from None


CHECKS: list[tuple[str, Callable[[Settings], str]]] = [
    ("export", check_export),
    ("insights", check_insights),
    ("timezone", check_timezone),
    ("taxonomy", check_taxonomy),
    ("ollama", check_ollama),
]


def settings_for(args: argparse.Namespace) -> Settings:
    """--config given = must exist; otherwise ./config/config.yaml if present."""
    cfg_path = args.config or DEFAULT_CONFIG
    cfg = load_config(cfg_path, required=args.config is not None)
    return resolve(cfg, getattr(args, "export", None), getattr(args, "out", None))


def doctor(args: argparse.Namespace) -> bool:
    """Prints a PASS/WARN/FAIL table; returns False only when something FAILs."""
    results: list[tuple[str, str, str]] = []
    try:
        s = settings_for(args)
        cfg_path = args.config or DEFAULT_CONFIG
        results.append(("config", "PASS", str(cfg_path) if cfg_path.exists() else "defaults"))
    except SystemExit as exc:
        results.append(("config", "FAIL", str(exc)))
    else:
        for name, check in CHECKS:
            try:
                results.append((name, "PASS", check(s)))
            except Warn as exc:
                results.append((name, "WARN", str(exc)))
            except SystemExit as exc:
                results.append((name, "FAIL", str(exc)))
    for name, status, detail in results:
        detail = detail.removeprefix("[!] ").replace("\n", " ")
        print(f"{status}  {name:<9} {detail}")
    return all(status != "FAIL" for _, status, _ in results)


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
            "export",
            nargs="?",
            type=Path,
            help="Instagram export .zip or folder (default: paths.ig_export, "
            "else the newest instagram-*.zip in ./data/ or ./)",
        )
        p.add_argument(
            "--config",
            type=Path,
            help="YAML config file (default: ./config/config.yaml if it exists)",
        )
        p.add_argument(
            "--out", type=Path, help="output vault folder (default: paths.out or vault/)"
        )
    sub.add_parser("shop-catalog", help="shop listing page -> Meta catalog CSV (see --help)")
    args = ap.parse_args(argv)

    if args.command == "init":
        init(args.dir)
    elif args.command == "doctor":
        if not doctor(args):
            raise SystemExit(1)
    else:
        build(settings_for(args))
