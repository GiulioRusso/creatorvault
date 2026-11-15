"""Obsidian vault output: notes, Dataview index, review CSV."""

from __future__ import annotations

import csv
import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from creatorvault.dedup import pub_ref
from creatorvault.models import Content, log
from creatorvault.tagging.taxonomy import axis_names, axis_values

# Extensions treated as images (videos are archived but not embedded as an
# image in the note).
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len].strip("-") or "post"


def yaml_quote(value: Any) -> str:
    """Serializes a scalar value for the YAML frontmatter."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


MANIFEST = ".creatorvault-manifest.json"


def sync_manifest(out_dir: Path, written: list[Path]) -> None:
    """Deletes files a previous build generated and this one didn't, then
    records this build's files. Anything else in the vault (your own notes)
    is never touched."""
    manifest = out_dir / MANIFEST
    now = sorted({p.relative_to(out_dir).as_posix() for p in written})
    if manifest.exists():
        for rel in set(json.loads(manifest.read_text(encoding="utf-8"))) - set(now):
            (out_dir / rel).unlink(missing_ok=True)
    manifest.write_text(json.dumps(now, indent=1) + "\n", encoding="utf-8")


def copy_media(src: Path, dest: Path) -> None:
    """Copies unless an identical-looking file is already there."""
    if not dest.exists() or dest.stat().st_size != src.stat().st_size:
        shutil.copy2(src, dest)


def note_stem(content: Content) -> str:
    """Date + slug of the first publication: stable as reposts get added."""
    first = content.first
    return f"{first.timestamp:%Y-%m-%d}-{slugify(first.title)}"


def write_notes(
    contents: list[Content], out_dir: Path, attachments_name: str, max_hashtags: int = 5
) -> list[Path]:
    """Writes one note per content; returns every file written (notes + media)."""
    notes_dir = out_dir / "posts"
    att_dir = out_dir / attachments_name
    notes_dir.mkdir(parents=True, exist_ok=True)
    att_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for content in contents:
        first, best = content.first, content.best
        stem = note_stem(content)
        note_path = notes_dir / f"{stem}.md"

        # Copy media and build the embeds
        embeds = []
        media = content.media
        for i, src in enumerate(media, 1):
            ext = src.suffix.lower()
            dest_name = f"{stem}-{i:02d}{ext}" if len(media) > 1 else f"{stem}{ext}"
            dest = att_dir / dest_name
            copy_media(src, dest)
            written.append(dest)
            if ext in IMAGE_EXT:
                embeds.append(f"![[{dest_name}]]")
            else:
                embeds.append(f"[[{dest_name}]]")

        # Frontmatter
        fm: list[str] = ["---"]
        fm.append(f"date: {first.timestamp:%Y-%m-%d}")
        fm.append(f"year: {first.timestamp.year}")
        fm.append(f"time: {first.timestamp:%H:%M}")
        fm.append(f"type: {'carousel' if len(media) > 1 else 'single'}")
        if best.permalink:
            fm.append(f"permalink: {yaml_quote(best.permalink)}")
        if content.best_tier:
            fm.append(f"tier: {content.best_tier}")
        fm.append(f"status: {content.status}")
        dates = [f"{p.timestamp:%Y-%m-%d}" for p in content.published]
        fm.append(f"times_published: {len(dates)}")
        if dates:
            fm.append(f"first_published: {dates[0]}")
            fm.append(f"last_published: {dates[-1]}")
            fm.append(f"published: [{', '.join(dates)}]")
        if content.drafts:
            ids = ", ".join(yaml_quote(d.draft_id) for d in content.drafts)
            fm.append(f"draft_ids: [{ids}]")
        if content.photo_ids:
            fm.append(f"photo_ids: [{', '.join(yaml_quote(i) for i in content.photo_ids)}]")
        if content.best_engagement is not None:
            fm.append(f"best_engagement: {int(content.best_engagement)}")
        n_hashtags = len(content.hashtags_original)
        fm.append(f"hashtags_original_count: {n_hashtags}")
        for metric, value in sorted(best.metrics.items()):
            if metric == "engagement_rate":
                fm.append(f"{metric}: {value}")
            else:
                fm.append(f"{metric}: {int(value)}")

        all_tags = ["post"]
        for axis, values in content.tags.items():
            for v in values:
                all_tags.append(f"{axis}/{v}")
        if content.best_tier:
            all_tags.append(f"tier/{content.best_tier}")
        if len(dates) > 1:
            all_tags.append("repost/yes")
        if n_hashtags > max_hashtags:
            all_tags.append("lint/too-many-hashtags")
        fm.append("tags:")
        for t in all_tags:
            fm.append(f"  - {t}")
        fm.append("---")

        body = ["", f"# {content.title}", ""]
        body += embeds
        # The caption goes in a code block for two reasons: hashtags inside
        # it would otherwise get indexed by Obsidian as real tags (polluting
        # the taxonomy), and this way it's copyable with one click when you
        # want to repost.
        caption = content.caption.strip() or "(no caption)"
        ready = content.ready_caption or "(no caption)"
        body += ["", "## Ready to post", "", "```text", ready, "```", ""]
        body += ["## Original caption", "", "```text", caption, "```", ""]
        for note in (content.match_note, content.review_note):
            if note:
                body += ["> [!warning] Needs review", f"> {note}", ""]
        body += publications_table(content)
        if best.permalink:
            body += [f"[Open on Instagram]({best.permalink})", ""]

        note_path.write_text("\n".join(fm + body), encoding="utf-8")
        written.append(note_path)

    return written


def publications_table(content: Content) -> list[str]:
    rows = [
        "## Publications",
        "",
        "| Date | Source | Link | Reach | Engagement | Rate | Tier |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in sorted(content.publications, key=lambda p: p.timestamp):
        if p.draft_id:
            source, link = "Meta draft", f"`{p.draft_id}`"
        else:
            source, link = "Instagram", f"[open]({p.permalink})" if p.permalink else ""
        m = p.metrics
        cells = [
            f"{p.timestamp:%Y-%m-%d %H:%M}",
            source,
            link,
            str(int(m["reach"])) if "reach" in m else "",
            str(int(m["engagement"])) if "engagement" in m else "",
            str(m.get("engagement_rate", "")),
            p.tier or "",
        ]
        rows.append("| " + " | ".join(cells) + " |")
    return [*rows, ""]


def drafts_report(contents: list[Content]) -> list[dict[str, Any]]:
    """One row per Meta draft. The newest draft of a content is the one to
    keep; it duplicates the published post, if any. Older drafts of the same
    content duplicate the kept one: those are safe to delete in Meta."""
    rows = []
    for content in contents:
        drafts = sorted(content.drafts, key=lambda d: d.timestamp, reverse=True)
        for k, d in enumerate(drafts):
            if k:
                duplicate_of = drafts[0].draft_id
            elif content.published:
                duplicate_of = pub_ref(content.published[0])
            else:
                duplicate_of = ""
            rows.append(
                {
                    "draft_id": d.draft_id,
                    "updated": f"{d.timestamp:%Y-%m-%d}",
                    "content": note_stem(content),
                    "status": content.status,
                    "duplicate_of": duplicate_of,
                }
            )
    return rows


def write_index(out_dir: Path, taxonomy: dict[str, Any]) -> Path:
    """Creates an index note with ready-to-use Dataview queries."""
    axes = axis_names(taxonomy)
    primary = axes[0] if axes else "program"
    secondary = axes[-1] if len(axes) > 1 else primary
    primary_vals = axis_values(taxonomy.get(primary, {}))
    secondary_vals = axis_values(taxonomy.get(secondary, {}))
    example_primary = primary_vals[0] if primary_vals else "apollo"
    example_secondary = secondary_vals[0] if secondary_vals else "anecdote"

    lines = [
        "---",
        "tags:",
        "  - index",
        "---",
        "",
        "# Post Archive",
        "",
        "> Requires the **Dataview** plugin (Settings -> Community plugins).",
        "",
        "## Best of each year",
        "",
        "```dataview",
        "TABLE date, engagement, engagement_rate, tags",
        'FROM "posts"',
        'WHERE tier = "top"',
        "SORT year DESC, engagement DESC",
        "```",
        "",
        f"## What I've already covered, by {primary}",
        "",
        "```dataview",
        "TABLE length(rows) AS count, max(rows.engagement) AS peak",
        'FROM "posts"',
        "FLATTEN tags AS tag",
        f'WHERE startswith(tag, "{primary}/")',
        "GROUP BY tag",
        "SORT count DESC",
        "```",
        "",
        "## Content gaps",
        "",
        f"What I've covered on `{example_primary}` without ever using the "
        f"`{example_secondary}` angle. Swap the two values to see what's missing.",
        "",
        "```dataview",
        "LIST",
        'FROM "posts"',
        f'WHERE contains(tags, "{primary}/{example_primary}")',
        f'  AND !contains(tags, "{secondary}/{example_secondary}")',
        "```",
        "",
        "## Ready to publish",
        "",
        "Drafts that never went out, oldest first.",
        "",
        "```dataview",
        "TABLE date, photo_ids, draft_ids",
        'FROM "posts"',
        'WHERE status = "draft"',
        "SORT date ASC",
        "```",
        "",
        "## Reposts: did they work?",
        "",
        "```dataview",
        "TABLE times_published, published, best_engagement, tier",
        'FROM "posts"',
        "WHERE times_published > 1",
        "SORT best_engagement DESC",
        "```",
        "",
        "## Strong and not posted in 12+ months",
        "",
        "```dataview",
        "TABLE last_published, best_engagement, times_published",
        'FROM "posts"',
        'WHERE tier = "top" AND last_published AND last_published <= date(today) - dur(1 year)',
        "SORT best_engagement DESC",
        "LIMIT 25",
        "```",
        "",
        "## Redundant Meta drafts",
        "",
        "Drafts that repeat a published post or another draft: see drafts_report.csv.",
        "",
        "```dataview",
        "TABLE status, draft_ids, last_published",
        'FROM "posts"',
        'WHERE length(draft_ids) > 1 OR status = "published+draft"',
        "SORT file.name ASC",
        "```",
        "",
        "## Too many hashtags in the original",
        "",
        'These would fail as scheduled posts: use the note\'s "Ready to post" caption.',
        "",
        "```dataview",
        "TABLE hashtags_original_count, date",
        'FROM "posts"',
        'WHERE contains(tags, "lint/too-many-hashtags")',
        "SORT hashtags_original_count DESC",
        "```",
        "",
        "## Available axes",
        "",
    ]
    for axis in axes:
        vals = ", ".join(f"`#{axis}/{v}`" for v in axis_values(taxonomy[axis]))
        lines.append(f"- **{axis}**: {vals}")
    lines.append("")
    path = out_dir / "Post Archive.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_review(
    review: list[dict[str, Any]], out_dir: Path, name: str = "review.csv"
) -> list[Path]:
    """Writes the CSV when there are rows; returns the files written."""
    if not review:
        return []
    path = out_dir / name
    fields = sorted({k for r in review for k in r})
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(review)
    log(f"[!] {len(review)} row(s) to review by hand: {path}")
    return [path]
