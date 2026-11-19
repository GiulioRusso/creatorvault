"""Meta Business Suite drafts, from files in paths.meta_drafts.

Business Suite doesn't export drafts. The folder can hold:

- `meta-drafts-*.zip` files downloaded by the browser script
  (`creatorvault drafts-script`), each with its own drafts.json and media;
- a hand-made `drafts.json`, with the images next to it:

    [{"id": "531138529578816", "caption": "...", "media": ["531138529578816.jpg"],
      "updated": "2024-08-22", "platforms": ["facebook", "instagram"]}]

The same draft can appear in several of them (overlapping exports): the
entry with the latest `updated` wins.
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from creatorvault.models import META_DRAFT, Publication, log

DRAFTS_JSON = "drafts.json"
EXPORT_ZIPS = "*.zip"


def _load(path: Path) -> list:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[!] Invalid JSON in {path} ({exc})") from None
    if not isinstance(raw, list):
        raise SystemExit(f"[!] {path} must hold a list of drafts.")
    return raw


def _parse(raw: list, folder: Path, origin: str) -> list[Publication]:
    drafts = []
    for entry in raw:
        draft_id = str(entry.get("id") or "").strip()
        if not draft_id:
            log(f"[!] Meta draft without an id in {origin}: skipped.")
            continue
        content_type = entry.get("content_type", "posts")
        if content_type not in ("posts", "reels"):
            raise SystemExit(f"[!] Meta draft {draft_id}: content_type must be posts or reels.")
        try:
            updated = datetime.fromisoformat(str(entry["updated"]))
        except (KeyError, ValueError):
            raise SystemExit(f"[!] Meta draft {draft_id}: 'updated' must be a YYYY-MM-DD date.")
        updated = updated.replace(tzinfo=UTC) if updated.tzinfo is None else updated.astimezone(UTC)
        media = []
        for name in entry.get("media") or []:
            if (folder / name).is_file():
                media.append(folder / name)
            else:
                log(f"[!] Meta draft {draft_id}: {name} not found in {origin}.")
        drafts.append(
            Publication(
                key=f"draft-{draft_id}",
                timestamp=updated,
                caption=entry.get("caption") or "",
                media=media,
                source=META_DRAFT,
                draft_id=draft_id,
                content_type=content_type,
            )
        )
    return drafts


def _extract(archive: Path, workdir: Path) -> Path:
    dest = workdir / archive.stem
    try:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                # The export is flat: anything in a folder (e.g. __MACOSX/ after a
                # re-zip) or hidden is skipped, so nothing lands outside dest.
                if info.is_dir() or "/" in info.filename or info.filename.startswith("."):
                    continue
                zf.extract(info, dest)
    except zipfile.BadZipFile:
        raise SystemExit(f"[!] {archive} is not a readable ZIP.") from None
    if not (dest / DRAFTS_JSON).is_file():
        raise SystemExit(f"[!] {archive.name} has no {DRAFTS_JSON}: not a drafts export.")
    return dest


def parse_meta_drafts(folder: Path, workdir: Path | None = None) -> list[Publication]:
    """Drafts from every export zip and drafts.json in folder. Zips are
    extracted into workdir, which must outlive the use of the media paths
    (a temporary folder is used, and kept, when none is given)."""
    if not folder.is_dir():
        return []
    sources: list[tuple[list, Path, str]] = []
    if (folder / DRAFTS_JSON).is_file():
        sources.append((_load(folder / DRAFTS_JSON), folder, DRAFTS_JSON))
    archives = sorted(folder.glob(EXPORT_ZIPS))
    if archives and workdir is None:
        workdir = Path(tempfile.mkdtemp(prefix="creatorvault-drafts-"))
    for archive in archives:
        root = _extract(archive, workdir / "meta-drafts")
        sources.append((_load(root / DRAFTS_JSON), root, archive.name))

    latest: dict[str, Publication] = {}
    for raw, root, origin in sources:
        for draft in _parse(raw, root, origin):
            kept = latest.get(draft.draft_id)
            if kept is None or draft.timestamp >= kept.timestamp:
                latest[draft.draft_id] = draft
    drafts = list(latest.values())
    for draft in drafts:
        if not draft.media:
            log(f"[!] Meta draft {draft.draft_id} has no image: its note will have no embed.")
    names = ", ".join(origin for _, _, origin in sources)
    log(f"[i] Found {len(drafts)} Meta draft(s) in {folder} ({names or 'no files'}).")
    return drafts
