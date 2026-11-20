"""Content pool: <vault>/pool/<slug>/post.md + media, one folder per content.

No publication dates anywhere (folder names, filenames, frontmatter), so the
pool is a reusable stock of content rather than a history. The format is
documented in the README (Content pool).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from creatorvault.models import Content, log
from creatorvault.writers.obsidian import copy_media, fence_for, slugify

# Marks the folders the build owns. Hand-written posts say `origin: manual`
# and are never touched.
ORIGIN = "archive"


def is_generated(post: Path) -> bool:
    head = post.read_text(encoding="utf-8", errors="ignore").split("\n---\n")[0]
    return re.search(rf"^origin: {ORIGIN}$", head, re.M) is not None


def pool_title(content: Content) -> str:
    """The caption's first line; never the publication date fallback."""
    title = content.title
    return f"Post {content.id}" if title.startswith("Post from ") else title


def post_md(content: Content, media: list[str], origin: str = ORIGIN) -> str:
    kinds = sorted({p.content_type for p in content.publications})
    fm = ["---", f"id: {content.id}", f"origin: {origin}"]
    fm.append(f"content_type: {'reels' if 'reels' in kinds else 'posts'}")
    fm.append(f"format: {'carousel' if len(media) > 1 else 'single'}")
    fm.append(f"media: [{', '.join(media)}]")
    if content.top_percent is not None:
        fm.append(f"top_percent: {content.top_percent}")
    tags = [f"{axis}/{v}" for axis, values in content.tags.items() for v in values]
    fm += ["tags:", *(f"  - {t}" for t in tags)] if tags else ["tags: []"]
    fm.append("---")
    caption = content.ready_caption or "(no caption)"
    fence = fence_for(caption)
    body = ["", f"# {pool_title(content)}", ""]
    body += [f"![]({name})" for name in media]
    body += ["", "## Description", "", f"{fence}text", caption, fence, ""]
    return "\n".join(fm + body)


def write_pool(contents: list[Content], out: Path) -> dict[str, str]:
    """<out>/<slug>/post.md + 01.jpg, 02.jpg... Rebuilt in place: generated
    folders no longer needed are removed; anything else is left alone.
    Returns content id -> slug, so archive notes can embed the pool's media."""
    out.mkdir(parents=True, exist_ok=True)
    generated = {p.parent for p in out.glob("*/post.md") if is_generated(p)}
    used = {d.name for d in out.iterdir() if d.is_dir()} - {d.name for d in generated}
    slugs: dict[str, str] = {}
    for content in contents:
        slug = base = slugify(pool_title(content))
        n = 2
        while slug in used:
            slug, n = f"{base}-{n}", n + 1
        used.add(slug)
        slugs[content.id] = slug
        folder = out / slug
        folder.mkdir(exist_ok=True)
        media = []
        for i, src in enumerate(content.media, 1):
            media.append(f"{i:02d}{src.suffix.lower()}")
            copy_media(src, folder / media[-1])
        for stale in folder.iterdir():
            if stale.name not in {"post.md", *media}:
                shutil.rmtree(stale) if stale.is_dir() else stale.unlink()
        (folder / "post.md").write_text(post_md(content, media), encoding="utf-8")
    for folder in generated - {out / s for s in slugs.values()}:
        shutil.rmtree(folder)
    log(f"[OK] Content pool: {len(contents)} post(s) in {out}")
    return slugs
