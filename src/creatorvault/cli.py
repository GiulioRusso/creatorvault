"""Command-line entry point: init, doctor, build, queue, catalog.

Every option lives in the config file; the only flag is --config."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from importlib.resources import files
from pathlib import Path

from creatorvault.config import CatalogConfig, Settings, load_config, load_timezone, resolve
from creatorvault.dedup import dedup
from creatorvault.hashtags import ready_caption
from creatorvault.insights.meta import (
    discover_insight_files,
    load_table,
    map_columns,
    parse_insights,
)
from creatorvault.join import join_posts
from creatorvault.models import RUN_LOG, Content, log
from creatorvault.pool import write_pool
from creatorvault.queue import pick, slots, write_queue
from creatorvault.ranking import assign_ranks
from creatorvault.review import Reviewer, check_local, review_duplicates, review_joins
from creatorvault.sources.instagram import (
    find_content_jsons,
    metadata_type,
    parse_ig_export,
    prepare_export,
)
from creatorvault.sources.meta_drafts import parse_meta_drafts
from creatorvault.tagging import ollama
from creatorvault.tagging.taxonomy import axis_names
from creatorvault.writers.obsidian import POOL, write_notes, write_review

DEFAULT_CONFIG = Path("config/config.yaml")
TEMPLATES = {"config.yaml": "config.yaml"}


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------


def init(dest: Path) -> None:
    """Copies the self-contained config template into dest. Never overwrites."""
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


def tag(posts: list, taxonomy: dict, s: Settings) -> None:
    """Tags in place. Ollama down or model missing = warning, never an error."""
    if not s.tag_enabled:
        log("[i] Tagging disabled by config: no semantic tags.")
        return
    if not taxonomy:
        if s.tag_required:
            raise SystemExit("[!] Tagging is required: add taxonomy categories to your config.")
        log("[!] No taxonomy in config: tagging disabled (`creatorvault init`).")
        return
    try:
        ollama.check_model(s.tag_model)
        # Changing categories or models must not reuse obsolete labels.
        signature = json.dumps([s.tag_model, taxonomy], sort_keys=True)
        digest = hashlib.sha256(signature.encode()).hexdigest()[:12]
        cache = s.cache_dir / f"tags_cache-{digest}.json"
        ollama.tag_posts(posts, taxonomy, s.tag_model, s.batch_size, cache)
    except SystemExit as exc:
        if s.tag_required:
            raise SystemExit(f"[!] Tagging is required: {exc}") from None
        log(f"[!] Tagging disabled: {str(exc).removeprefix('[!] ')}")


def print_summary(rows: list[tuple[str, int]]) -> None:
    width = max(len(label) for label, _ in rows)
    log("")
    for label, value in rows:
        log(f"  {label:<{width}}  {value:>6}")


@dataclass
class Archive:
    """Everything build and queue need, before anything is written."""

    contents: list[Content]
    taxonomy: dict
    n_read: int
    n_drafts: int
    n_contents: int
    n_groups: int
    review_audit: list[dict] = field(default_factory=list)


def local_reviewer(s: Settings) -> Reviewer | None:
    """The local model that settles ambiguous joins and duplicates. When it
    can't run, ambiguous cases stay unresolved (separate contents, no
    metrics): nothing is left for you to review by hand."""
    if not s.review.enabled:
        return None
    try:
        check_local(s.review.model)
    except SystemExit as exc:
        if s.tag_required:
            raise SystemExit(f"[!] Automated review is required: {exc}") from None
        log(f"[!] Automated review skipped: {str(exc).removeprefix('[!] ')}")
        return None
    reviewer = Reviewer(s.review, s.cache_dir / "review-cache.json")
    reviewer.checked = True
    return reviewer


def collect(s: Settings, workdir: Path) -> Archive:
    """Export + insights + drafts -> tagged, deduplicated contents. ZIPs are
    extracted into workdir, which must outlive the use of the media paths."""
    exports = s.ig_exports or [s.ig_export]
    for export in exports:
        if not export.exists():
            raise SystemExit(f"[!] Instagram export not found: {export}")
    insight_files = discover_insight_files(s.insights_dir)
    tz = load_timezone(s.insights_tz_name)
    taxonomy = s.taxonomy
    s.cache_dir.mkdir(parents=True, exist_ok=True)

    # 1. Instagram export
    roots = []
    for n, export in enumerate(exports):
        part = workdir / f"part-{n}"
        part.mkdir()
        roots.append(prepare_export(export, part))
    posts_by_key = {}
    for root in roots:
        other_roots = [p for p in roots if p != root]
        if not find_content_jsons(root, s.content_types):
            log(f"[i] Export part {root} has no selected metadata: using its media only.")
            continue
        for post in parse_ig_export(root, other_roots, s.content_types):
            # Split downloads can repeat the same metadata. That is one
            # publication, even when repost deduplication is disabled.
            posts_by_key.setdefault((post.content_type, post.key, post.caption), post)
    posts = sorted(posts_by_key.values(), key=lambda p: p.timestamp)
    if not posts:
        raise SystemExit(f"[!] No {'/'.join(s.content_types)} found in the export.")

    # 2. Insights + join
    if not insight_files:
        log("[i] No insights: archive without metrics.")
    insights = parse_insights(insight_files, tz)
    insights = [
        r for r in insights if not r.get("content_type") or r["content_type"] in s.content_types
    ]
    ambiguous = join_posts(posts, insights, s.tolerance_minutes)
    reviewer = local_reviewer(s) if ambiguous or s.dedup.enabled else None
    if reviewer is not None:
        review_joins(posts, insights, ambiguous, reviewer)
    assign_ranks(posts, s.selection.metric, s.selection.scope)

    # 3. Meta drafts (no metrics) + repost detection across everything
    drafts = [d for d in parse_meta_drafts(s.meta_drafts) if d.content_type in s.content_types]
    contents, borderline = dedup(posts + drafts, s.dedup)
    if reviewer is not None and borderline:
        contents = review_duplicates(contents, borderline, reviewer, s.dedup)
    # Without a reviewer, borderline pairs simply stay separate contents.
    n_contents = len(contents)
    n_groups = sum(len(c.publications) > 1 for c in contents)

    sel = s.selection
    if not sel.keeps_all:
        contents = [
            c for c in contents if c.top_percent is not None and c.top_percent <= sel.top_percentile
        ]
        log(f"[i] Top {sel.top_percentile:g}% on {sel.metric}: {len(contents)} content(s) kept.")
        if not contents:
            log("[!] Nothing ranked: no insights? Set selection.top_percentile: 100 to keep all.")

    # 4. Tags, then the ready-to-post caption (taxonomy hashtags need the tags)
    tag(contents, taxonomy, s)
    for c in contents:
        c.ready_caption = ready_caption(c.caption, c.tags, s.hashtags)
    return Archive(
        contents,
        taxonomy,
        len(posts),
        len(drafts),
        n_contents,
        n_groups,
        reviewer.audit if reviewer is not None else [],
    )


def rerun_command(config: Path) -> str:
    env = os.environ.get("PYTHONPATH")
    prefix = f"PYTHONPATH={shlex.quote(env)} " if env else ""
    return (
        f"cd {shlex.quote(os.getcwd())} && {prefix}{shlex.quote(sys.executable)} "
        f"-m creatorvault build --config {shlex.quote(str(config))}"
    )


def build(s: Settings, config: Path) -> None:
    RUN_LOG.clear()
    started = datetime.now()
    # The extracted export is only needed while the media are copied.
    with tempfile.TemporaryDirectory(prefix="creatorvault-") as tmp:
        a = collect(s, Path(tmp))
        out_dir = write_vault(s, a)
    command = rerun_command(config)
    log(f"\n[OK] Vault in {out_dir}: open it in Obsidian and start from 'Review.md'.")
    elapsed = str(datetime.now() - started).split(".")[0]
    header = [
        f"# creatorvault build, {started:%Y-%m-%d %H:%M}, {elapsed} elapsed",
        f"# rerun: {command}",
        "",
    ]
    (out_dir / "run.log").write_text("\n".join(header + RUN_LOG) + "\n", encoding="utf-8")


def write_vault(s: Settings, a: Archive) -> Path:
    out_dir = s.out_base
    if s.timestamped_out:
        # Each run gets its own folder, so a rerun never touches a previous archive.
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = s.out_base.parent / f"{s.out_base.name}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    slugs = write_pool(a.contents, out_dir / POOL)
    write_notes(a.contents, out_dir, slugs)
    summary = [
        ("publications read", a.n_read),
        ("unique contents", a.n_contents),
        ("duplicate groups", a.n_groups),
        ("drafts", a.n_drafts),
        ("notes written", len(a.contents)),
        ("decided by the local model", len(a.review_audit)),
        ("untagged", sum(not c.tags for c in a.contents)),
    ]
    write_review(out_dir, a.contents, slugs, summary, a.review_audit, a.taxonomy)
    print_summary(summary)
    return out_dir


# --------------------------------------------------------------------------
# queue
# --------------------------------------------------------------------------


def queue(s: Settings) -> None:
    q = s.queue
    start = q.first_day()
    with tempfile.TemporaryDirectory(prefix="creatorvault-") as tmp:
        a = collect(s, Path(tmp))
        axes = axis_names(a.taxonomy)
        chosen = pick(a.contents, q.next, start, q.min_repost_months, axes[0] if axes else None)
        path = write_queue(chosen, slots(start, q.days, len(chosen)), q.time, q.out)
    log(f"\n[OK] {len(chosen)} post(s) queued in {path.parent} (checklist: {path.name}).")


# --------------------------------------------------------------------------
# catalog
# --------------------------------------------------------------------------


def catalog(cfg: dict) -> None:
    c = CatalogConfig.from_config(cfg)
    try:
        from creatorvault.shop_catalog import build_catalog, write_catalog_csv
    except ImportError:
        raise SystemExit("[!] The catalog needs the shop extra: pip install '.[shop]'") from None
    rows = build_catalog(c.shop_url, c.currency, c.brand)
    if not rows:
        raise SystemExit("[!] No product parsed successfully: nothing written.")
    write_catalog_csv(rows, c.out)
    log(f"\n[OK] {len(rows)} product(s) written to {c.out}")


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------


class Warn(Exception):
    """A doctor check that found something degraded but not blocking."""


def check_export(s: Settings) -> str:
    exports = s.ig_exports or [s.ig_export]
    results = []
    for export in exports:
        try:
            results.append(check_export_path(export, s.content_types))
        except SystemExit as exc:
            if len(exports) > 1 and "no " in str(exc) and " JSON" in str(exc):
                results.append("media-only part")
            else:
                raise
    if all(result == "media-only part" for result in results):
        raise SystemExit(f"no {'/'.join(s.content_types)} JSON in any export part")
    return "; ".join(results)


def check_export_path(path: Path, content_types: list[str] | None = None) -> str:
    selected = content_types if content_types is not None else ["posts"]
    if not path.exists():
        raise SystemExit(f"not found: {path}")
    if path.is_dir():
        found = find_content_jsons(path, selected)
        if not found:
            raise SystemExit(f"no {'/'.join(selected)} JSON in the export folder")
        return "; ".join(f"{kind} JSON: {p.relative_to(path)}" for p, kind in found)
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        raise SystemExit(f"not a readable ZIP: {path}") from None
    found = sorted(n for n in names if metadata_type(Path(n)) in selected)
    if found:
        return f"{'/'.join(selected)} JSON: {found[0]}"
    raise SystemExit(f"no {'/'.join(selected)} JSON in the ZIP (did you pick JSON, not HTML?)")


def check_insights(s: Settings) -> str:
    paths = discover_insight_files(s.insights_dir)
    if not paths:
        raise Warn(f"no insights in {s.insights_dir}: archive without metrics")
    for path in paths:
        header, _rows = load_table(path)
        if "publish_time" not in map_columns(header):
            raise SystemExit(f"{path.name}: no publish-time column in {header}")
    return f"{len(paths)} file(s), publish-time column found"


def check_drafts(s: Settings) -> str:
    if not (s.meta_drafts / "drafts.json").exists():
        return f"no {s.meta_drafts / 'drafts.json'} (optional)"
    return f"{len(parse_meta_drafts(s.meta_drafts))} draft(s)"


def check_timezone(s: Settings) -> str:
    load_timezone(s.insights_tz_name)
    return s.insights_tz_name


def check_taxonomy(s: Settings) -> str:
    if not s.taxonomy:
        if s.tag_required and s.tag_enabled:
            raise SystemExit("tagging required but no taxonomy configured")
        raise Warn("no taxonomy in config: tagging disabled")
    axes = axis_names(s.taxonomy)
    return f"{len(axes)} axis/axes: {', '.join(axes)}"


def check_ollama(s: Settings) -> str:
    if not s.tag_enabled:
        return "tagging disabled, skipped"
    try:
        return ollama.check_model(s.tag_model)
    except SystemExit as exc:
        if s.tag_required:
            raise
        raise Warn(f"{exc}; tagging will be skipped") from None


def check_review(s: Settings) -> str:
    return check_local(s.review.model) if s.review.enabled else "automated review disabled"


CHECKS: list[tuple[str, Callable[[Settings], str]]] = [
    ("export", check_export),
    ("insights", check_insights),
    ("drafts", check_drafts),
    ("timezone", check_timezone),
    ("taxonomy", check_taxonomy),
    ("ollama", check_ollama),
    ("review", check_review),
]


def settings_for(args: argparse.Namespace) -> Settings:
    return resolve(load_config(args.config))


def doctor(args: argparse.Namespace) -> bool:
    """Prints a PASS/WARN/FAIL table; returns False only when something FAILs."""
    results: list[tuple[str, str, str]] = []
    try:
        s = settings_for(args)
        results.append(("config", "PASS", str(args.config)))
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
    ap = argparse.ArgumentParser(
        prog="creatorvault",
        description="Turn your own social-media exports into a searchable Obsidian archive. "
        "Every option is set in the config file.",
    )
    sub = ap.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="create a commented config file")
    p_init.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_CONFIG.parent,
        help="destination folder (default: ./config)",
    )
    for name, help_ in (
        ("build", "build the Obsidian vault: dated archive, content pool, Review.md"),
        ("doctor", "check config, exports, timezone, taxonomy and Ollama"),
        ("queue", "prepare images + captions for the next posting slots (queue: section)"),
        ("catalog", "shop listing page -> Meta catalog CSV (catalog: section)"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument(
            "--config",
            type=Path,
            default=DEFAULT_CONFIG,
            help=f"YAML config file (default: {DEFAULT_CONFIG})",
        )
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    if args.command == "init":
        init(args.dir)
    elif args.command == "doctor":
        if not doctor(args):
            raise SystemExit(1)
    elif args.command == "queue":
        queue(settings_for(args))
    elif args.command == "catalog":
        catalog(load_config(args.config))
    else:
        build(settings_for(args), args.config)
