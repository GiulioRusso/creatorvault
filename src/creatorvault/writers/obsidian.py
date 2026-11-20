"""Obsidian vault output: dated archive notes and the Review.md report."""

from __future__ import annotations

import filecmp
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from creatorvault.dedup import pub_ref
from creatorvault.models import Content
from creatorvault.tagging.taxonomy import axis_names, axis_values

# Extensions treated as images (the queue only takes images).
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


ARCHIVE = "archive"  # dated notes, one per content; the build owns this folder
POOL = "pool"  # undated post.md + media, see creatorvault.pool


def copy_media(src: Path, dest: Path) -> None:
    """Copies unless the existing media bytes are identical."""
    if not dest.exists() or not filecmp.cmp(src, dest, shallow=False):
        shutil.copy2(src, dest)


def fence_for(text: str) -> str:
    """A code fence longer than any backtick run inside text."""
    return "`" * max(3, max((len(m[0]) + 1 for m in re.finditer(r"`+", text)), default=3))


def note_stem(content: Content) -> str:
    """Date + slug of the first publication: stable as reposts get added."""
    first = content.first
    prefix = "reel-" if first.content_type == "reels" else ""
    return f"{first.timestamp:%Y-%m-%d}-{prefix}{slugify(first.title)}"


def write_notes(contents: list[Content], out_dir: Path, slugs: dict[str, str]) -> None:
    """One dated note per content in <out>/archive. The media stay in the
    pool (slugs: content id -> pool folder): embedded, never copied twice.
    Notes from a previous build that are no longer generated are removed."""
    notes_dir = out_dir / ARCHIVE
    notes_dir.mkdir(parents=True, exist_ok=True)

    written: set[Path] = set()
    for content in contents:
        first, best = content.first, content.best
        stem = note_stem(content)
        note_path = notes_dir / f"{stem}.md"
        folder = f"{POOL}/{slugs[content.id]}"

        embeds = []
        media = content.media
        for i, src in enumerate(media, 1):
            ext = src.suffix.lower()
            target = f"{folder}/{i:02d}{ext}"
            embeds.append(f"![[{target}]]")

        # Frontmatter
        fm: list[str] = ["---"]
        fm.append(f"date: {first.timestamp:%Y-%m-%d}")
        fm.append(f"year: {first.timestamp.year}")
        fm.append(f"time: {first.timestamp:%H:%M}")
        fm.append(f"type: {'carousel' if len(media) > 1 else 'single'}")
        content_types = sorted({p.content_type for p in content.publications})
        if "reels" in content_types:
            fm.append(f"content_types: [{', '.join(content_types)}]")
        if best.permalink:
            fm.append(f"permalink: {yaml_quote(best.permalink)}")
        if content.top_percent is not None:
            fm.append(f"top_percent: {content.top_percent}")
        fm.append(f'pool: "[[{folder}/post]]"')
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
        for metric, value in sorted(best.metrics.items()):
            if metric == "engagement_rate":
                fm.append(f"{metric}: {value}")
            else:
                fm.append(f"{metric}: {int(value)}")

        all_tags = ["post"] if "posts" in content_types else []
        if "reels" in content_types:
            all_tags.append("reel")
        for axis, values in content.tags.items():
            for v in values:
                all_tags.append(f"{axis}/{v}")
        if len(dates) > 1:
            all_tags.append("repost/yes")
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
        ready = content.ready_caption or "(no caption)"
        fence = fence_for(ready)
        body += ["", "## Description", "", f"{fence}text", ready, fence, ""]
        body += publications_table(content)
        if best.permalink:
            body += [f"[Open on Instagram]({best.permalink})", ""]

        note_path.write_text("\n".join(fm + body), encoding="utf-8")
        written.add(note_path)

    for stale in set(notes_dir.glob("*.md")) - written:
        stale.unlink()


def publications_table(content: Content) -> list[str]:
    rows = [
        "## Publications",
        "",
        "| Date | Source | Link | Reach | Engagement | Rate | Top % |",
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
            "" if p.top_percent is None else str(p.top_percent),
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


def queries(taxonomy: dict[str, Any]) -> list[str]:
    """Ready-to-use Dataview queries over the archive and the pool."""
    axes = axis_names(taxonomy)
    primary = axes[0] if axes else "topic"
    secondary = axes[-1] if len(axes) > 1 else primary
    primary_vals = axis_values(taxonomy.get(primary, {}))
    secondary_vals = axis_values(taxonomy.get(secondary, {}))
    example_primary = primary_vals[0] if primary_vals else "example"
    example_secondary = secondary_vals[0] if secondary_vals else "anecdote"

    lines = [
        "## Queries",
        "",
        "> Requires the **Dataview** plugin (Settings -> Community plugins).",
        "",
        "### Best of each year",
        "",
        "The top 10%. `top_percent: N` = in the best N% (per year or over the archive,",
        "as set by `selection.scope`).",
        "",
        "```dataview",
        "TABLE date, top_percent, engagement, engagement_rate, tags",
        f'FROM "{ARCHIVE}"',
        "WHERE top_percent <= 10",
        "SORT year DESC, top_percent ASC",
        "```",
        "",
        f"### What I've already covered, by {primary}",
        "",
        "```dataview",
        "TABLE length(rows) AS count, max(rows.engagement) AS peak",
        f'FROM "{ARCHIVE}"',
        "FLATTEN tags AS tag",
        f'WHERE startswith(tag, "{primary}/")',
        "GROUP BY tag",
        "SORT count DESC",
        "```",
        "",
        "### Content gaps",
        "",
        f"What I've covered on `{example_primary}` without ever using the "
        f"`{example_secondary}` angle. Swap the two values to see what's missing.",
        "",
        "```dataview",
        "LIST",
        f'FROM "{ARCHIVE}"',
        f'WHERE contains(tags, "{primary}/{example_primary}")',
        f'  AND !contains(tags, "{secondary}/{example_secondary}")',
        "```",
        "",
        "### Ready to publish",
        "",
        "Drafts that never went out, oldest first.",
        "",
        "```dataview",
        "TABLE date, photo_ids, draft_ids",
        f'FROM "{ARCHIVE}"',
        'WHERE status = "draft"',
        "SORT date ASC",
        "```",
        "",
        "### Reposts: did they work?",
        "",
        "```dataview",
        "TABLE times_published, published, best_engagement, top_percent",
        f'FROM "{ARCHIVE}"',
        "WHERE times_published > 1",
        "SORT best_engagement DESC",
        "```",
        "",
        "### Strong and not posted in 12+ months",
        "",
        "```dataview",
        "TABLE last_published, best_engagement, times_published",
        f'FROM "{ARCHIVE}"',
        "WHERE top_percent <= 25",
        "  AND last_published AND last_published <= date(today) - dur(1 year)",
        "SORT top_percent ASC, best_engagement DESC",
        "LIMIT 25",
        "```",
        "",
        "### Redundant Meta drafts",
        "",
        "Drafts that repeat a published post or another draft (see Meta drafts above).",
        "",
        "```dataview",
        "TABLE status, draft_ids, last_published",
        f'FROM "{ARCHIVE}"',
        'WHERE length(draft_ids) > 1 OR status = "published+draft"',
        "SORT file.name ASC",
        "```",
        "",
        "### Pool: best first",
        "",
        "```dataview",
        "TABLE content_type, format, top_percent, tags",
        f'FROM "{POOL}"',
        'WHERE file.name = "post"',
        "SORT top_percent ASC",
        "```",
        "",
        "### Pool: untagged",
        "",
        "```dataview",
        "LIST",
        f'FROM "{POOL}"',
        'WHERE file.name = "post" AND length(tags) = 0',
        "```",
        "",
        "## Available axes",
        "",
    ]
    for axis in axes:
        vals = ", ".join(f"`#{axis}/{v}`" for v in axis_values(taxonomy[axis]))
        lines.append(f"- **{axis}**: {vals}")
    lines.append("")
    return lines


def cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def table(header: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return [*lines, ""]


def write_review(
    out_dir: Path,
    contents: list[Content],
    slugs: dict[str, str],
    summary: list[tuple[str, int]],
    audit: list[dict[str, Any]],
    taxonomy: dict[str, Any],
) -> None:
    """Review.md: what the run did, what the model decided, what's left to look at."""
    lines = [
        "# Review",
        "",
        f"Dated notes in `{ARCHIVE}/`, undated reusable posts in `{POOL}/`.",
        "How this run went and how to rerun it: `run.log` (first lines).",
        "",
        "## Summary",
        "",
        *table(["", "count"], [[label, value] for label, value in summary]),
        "## Decisions by the local model",
        "",
    ]
    if audit:
        lines += table(
            ["case", "reference", "outcome", "confidence", "reason"],
            [
                [r["case"], r["reference"], r["outcome"], r["confidence"], r["reason"]]
                for r in audit
            ],
        )
    else:
        lines += ["None: no ambiguous join or duplicate needed the model.", ""]
    drafts = drafts_report(contents)
    if drafts:
        lines += ["## Meta drafts", "", "A draft with `duplicate_of` set is safe to delete.", ""]
        lines += table(list(drafts[0]), [list(d.values()) for d in drafts])
    untagged = [c for c in contents if not c.tags]
    if untagged and taxonomy:
        lines += ["## Untagged", ""]
        lines += [f"- [[{POOL}/{slugs[c.id]}/post|{c.title}]]" for c in untagged] + [""]
    lines += queries(taxonomy)
    (out_dir / "Review.md").write_text("\n".join(lines), encoding="utf-8")
