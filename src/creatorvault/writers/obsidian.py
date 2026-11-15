"""Obsidian vault output: notes, Dataview index, review CSV."""

from __future__ import annotations

import csv
import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from creatorvault.models import Post, log
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


def write_notes(posts: list[Post], out_dir: Path, attachments_name: str) -> list[Path]:
    """Writes one note per post; returns every file written (notes + media)."""
    notes_dir = out_dir / "posts"
    att_dir = out_dir / attachments_name
    notes_dir.mkdir(parents=True, exist_ok=True)
    att_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for post in posts:
        date_str = post.timestamp.strftime("%Y-%m-%d")
        stem = f"{date_str}-{slugify(post.title)}"
        note_path = notes_dir / f"{stem}.md"

        # Copy media and build the embeds
        embeds = []
        for i, src in enumerate(post.media, 1):
            ext = src.suffix.lower()
            dest_name = f"{stem}-{i:02d}{ext}" if len(post.media) > 1 else f"{stem}{ext}"
            dest = att_dir / dest_name
            copy_media(src, dest)
            written.append(dest)
            if ext in IMAGE_EXT:
                embeds.append(f"![[{dest_name}]]")
            else:
                embeds.append(f"[[{dest_name}]]")

        # Frontmatter
        fm: list[str] = ["---"]
        fm.append(f"date: {post.timestamp.strftime('%Y-%m-%d')}")
        fm.append(f"year: {post.timestamp.year}")
        fm.append(f"time: {post.timestamp.strftime('%H:%M')}")
        fm.append(f"type: {'carousel' if post.is_carousel else 'single'}")
        if post.permalink:
            fm.append(f"permalink: {yaml_quote(post.permalink)}")
        if post.tier:
            fm.append(f"tier: {post.tier}")
        for metric, value in sorted(post.metrics.items()):
            if metric == "engagement_rate":
                fm.append(f"{metric}: {value}")
            else:
                fm.append(f"{metric}: {int(value)}")

        all_tags = ["post"]
        for axis, values in post.tags.items():
            for v in values:
                all_tags.append(f"{axis}/{v}")
        if post.tier:
            all_tags.append(f"tier/{post.tier}")
        fm.append("tags:")
        for t in all_tags:
            fm.append(f"  - {t}")
        fm.append("---")

        body = ["", f"# {post.title}", ""]
        body += embeds
        # The caption goes in a code block for two reasons: hashtags inside
        # it would otherwise get indexed by Obsidian as real tags (polluting
        # the taxonomy), and this way it's copyable with one click when you
        # want to repost.
        body += ["", "## Caption", "", "```text", post.caption.strip() or "(no caption)", "```", ""]
        if post.match_note:
            body += ["> [!warning] Needs review", f"> {post.match_note}", ""]
        if post.permalink:
            body += [f"[Open on Instagram]({post.permalink})", ""]

        note_path.write_text("\n".join(fm + body), encoding="utf-8")
        written.append(note_path)

    return written


def write_index(posts: list[Post], out_dir: Path, taxonomy: dict[str, Any]) -> Path:
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
        "## Worth reposting: old but strong",
        "",
        "```dataview",
        "TABLE year, engagement_rate, tags",
        'FROM "posts"',
        'WHERE tier = "top" AND year <= date(today).year - 2',
        "SORT engagement_rate DESC",
        "LIMIT 25",
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
