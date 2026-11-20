"""`creatorvault import-drafts`: Meta drafts -> new folders in an existing pool.

Unlike `build`, it never rewrites what is already in the pool. It reads the
drafts in paths.meta_drafts (zips from `creatorvault drafts-script` and/or a
drafts.json), drops the ones that repeat a post already in the pool (same
photo code, same image or same caption, as in `build`), and writes each new
content as <pool>/<slug>/post.md + media with `origin: manual`, so later
builds leave it alone. A CSV report lists what happened to every draft.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from creatorvault.dedup import DedupConfig, dedup
from creatorvault.hashtags import ready_caption
from creatorvault.models import INSTAGRAM, Content, Publication, log
from creatorvault.pool import pool_title, post_md
from creatorvault.writers.obsidian import copy_media, slugify

MANUAL = "manual"
REPORT = "import-report.csv"
POOL_REF = "pool:"  # how pool posts are named in dedup (pub_ref) and the report
DESCRIPTION = re.compile(r"## Description\s*\n(`{3,})text\n(.*?)\n\1", re.S)


@dataclass
class DraftsImportConfig:
    """`drafts_import:` section."""

    pool_posts: Path | None = None  # pool folder that receives posts
    pool_reels: Path | None = None  # pool folder that receives reels
    report: Path | None = None  # default: <paths.meta_drafts>/import-report.csv
    dry_run: bool = False  # true = only the report, nothing written to the pools

    @classmethod
    def from_dict(cls, raw: Any) -> DraftsImportConfig:
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise SystemExit("[!] drafts_import must be a mapping.")
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise SystemExit(f"[!] Unknown drafts_import option(s): {', '.join(sorted(unknown))}")
        cfg = cls(**raw)
        for name in ("pool_posts", "pool_reels", "report"):
            value = getattr(cfg, name)
            setattr(cfg, name, Path(value) if value else None)
        cfg.dry_run = bool(cfg.dry_run)
        return cfg

    def pool_for(self, content_type: str) -> Path | None:
        return self.pool_reels if content_type == "reels" else self.pool_posts

    @property
    def pools(self) -> list[Path]:
        return [p for p in dict.fromkeys((self.pool_posts, self.pool_reels)) if p]


def front_matter(text: str) -> dict[str, Any]:
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    try:
        data = yaml.safe_load(m[1]) if m else {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def pool_publications(pool: Path) -> list[Publication]:
    """Every post already in a pool, as a publication dedup can compare with."""
    pubs = []
    for md in sorted(pool.glob("*/post.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        fm = front_matter(text)
        m = DESCRIPTION.search(text)
        media = [md.parent / str(name) for name in fm.get("media") or []]
        pubs.append(
            Publication(
                key=f"pool-{fm.get('id') or md.parent.name}",
                timestamp=datetime(1970, 1, 1, tzinfo=UTC),
                caption=m[2] if m else "",
                media=[p for p in media if p.is_file()][:1],
                permalink=f"{POOL_REF}{md.parent.name}",
                source=INSTAGRAM,
                content_type=str(fm.get("content_type") or "posts"),
            )
        )
    return pubs


def free_slug(pool: Path, base: str) -> str:
    slug, n = base, 2
    while (pool / slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def write_content(content: Content, pool: Path) -> Path:
    folder = pool / free_slug(pool, slugify(pool_title(content)))
    folder.mkdir(parents=True)
    media = []
    for i, src in enumerate(content.media, 1):
        ext = ".jpg" if src.suffix.lower() == ".jpeg" else src.suffix.lower()
        media.append(f"{i:02d}{ext}")
        copy_media(src, folder / media[-1])
    (folder / "post.md").write_text(post_md(content, media, origin=MANUAL), encoding="utf-8")
    return folder


@dataclass
class Plan:
    new: list[Content]
    rows: list[dict[str, str]]


def plan(
    drafts: list[Publication],
    pool_pubs: list[Publication],
    cfg: DedupConfig,
    borderline_hint: bool = True,
) -> Plan:
    """Which drafts are new contents, and a report row for every draft."""
    contents, borderline = dedup(pool_pubs + drafts, cfg)
    maybe: dict[str, str] = {}
    if borderline_hint:
        for row in borderline:
            for mine, other in (("a_ref", "b_ref"), ("b_ref", "a_ref")):
                if row[other].startswith(POOL_REF):
                    maybe.setdefault(row[mine], row[other].removeprefix(POOL_REF))
    new, rows = [], []
    for content in contents:
        if not content.drafts:
            continue
        in_pool = [p.permalink.removeprefix(POOL_REF) for p in content.published if p.permalink]
        latest = max(content.drafts, key=lambda p: p.timestamp)
        for draft in content.drafts:
            row = {
                "draft_id": draft.draft_id or "",
                "updated": f"{draft.timestamp:%Y-%m-%d}",
                "type": draft.content_type,
                "caption": " ".join(draft.caption.split())[:90],
                "status": "",
                "detail": "",
            }
            if in_pool:
                row.update(status="duplicate of pool", detail=", ".join(in_pool))
            elif draft is not latest:
                row.update(status="duplicate draft", detail=f"same as draft {latest.draft_id}")
            elif not content.media:
                row.update(status="skipped", detail="no media in the export")
            else:
                row["status"] = "new"
                if draft.draft_id in maybe:
                    row["detail"] = f"similar to {maybe[draft.draft_id]}: check it"
            rows.append(row)
        if not in_pool and content.media:
            new.append(content)
    return Plan(new, rows)


def write_report(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ["draft_id", "updated", "type", "caption", "status", "detail"]
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["status"], r["updated"])))


def import_drafts(
    drafts: list[Publication],
    cfg: DraftsImportConfig,
    dedup_cfg: DedupConfig,
    hashtags: Any,
    tagger: Any = None,
    report: Path | None = None,
) -> Plan:
    """Writes the new drafts into their pool (unless dry_run) and the report."""
    for pool in cfg.pools:
        if not pool.is_dir():
            raise SystemExit(f"[!] Pool folder not found: {pool}")
    pool_pubs = [p for pool in cfg.pools for p in pool_publications(pool)]
    log(f"[i] {len(pool_pubs)} post(s) already in the pool(s), {len(drafts)} draft(s) to check.")
    result = plan(drafts, pool_pubs, dedup_cfg)
    if tagger is not None and result.new:
        tagger(result.new)
    for content in result.new:
        content.ready_caption = ready_caption(content.caption, content.tags, hashtags)

    written: dict[str, str] = {}
    for content in result.new:
        kind = "reels" if any(p.content_type == "reels" for p in content.drafts) else "posts"
        pool = cfg.pool_for(kind)
        latest = max(content.drafts, key=lambda p: p.timestamp)
        if pool is None:
            written[latest.draft_id or ""] = f"no drafts_import.pool_{kind}: not written"
            continue
        if cfg.dry_run:
            written[latest.draft_id or ""] = f"would go to {pool.name}"
            continue
        folder = write_content(content, pool)
        written[latest.draft_id or ""] = str(folder.relative_to(pool.parent))
    for row in result.rows:
        if row["status"] == "new" and row["draft_id"] in written:
            where = written[row["draft_id"]]
            row["detail"] = f"{where}; {row['detail']}" if row["detail"] else where

    if report is not None:
        write_report(result.rows, report)
    counts: dict[str, int] = {}
    for row in result.rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "nothing to import"
    verb = "would be written" if cfg.dry_run else "written"
    log(f"[OK] Drafts: {summary}. {len(result.new)} new post(s) {verb}.")
    if report is not None:
        log(f"     Report: {report}")
    return result
