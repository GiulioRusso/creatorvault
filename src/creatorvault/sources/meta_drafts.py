"""Meta Business Suite drafts, from a hand-made drafts.json.

Business Suite doesn't export drafts, so they're collected separately into
<folder>/drafts.json, with the images next to it:

    [{"id": "531138529578816", "caption": "...", "media": ["531138529578816.jpg"],
      "updated": "2024-08-22", "platforms": ["facebook", "instagram"]}]
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from creatorvault.models import META_DRAFT, Publication, log


def parse_meta_drafts(folder: Path) -> list[Publication]:
    path = folder / "drafts.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[!] Invalid JSON in {path} ({exc})") from None
    if not isinstance(raw, list):
        raise SystemExit(f"[!] {path} must hold a list of drafts.")

    drafts = []
    for entry in raw:
        draft_id = str(entry.get("id") or "").strip()
        if not draft_id:
            log("[!] Meta draft without an id: skipped.")
            continue
        try:
            updated = datetime.fromisoformat(str(entry["updated"]))
        except (KeyError, ValueError):
            raise SystemExit(f"[!] Meta draft {draft_id}: 'updated' must be a YYYY-MM-DD date.")
        updated = updated.replace(tzinfo=UTC) if updated.tzinfo is None else updated.astimezone(UTC)
        media = []
        for name in entry.get("media") or []:
            if (folder / name).exists():
                media.append(folder / name)
            else:
                log(f"[!] Meta draft {draft_id}: {name} not found in {folder}.")
        if not media:
            log(f"[!] Meta draft {draft_id} has no image: its note will have no embed.")
        drafts.append(
            Publication(
                key=f"draft-{draft_id}",
                timestamp=updated,
                caption=entry.get("caption") or "",
                media=media,
                source=META_DRAFT,
                draft_id=draft_id,
            )
        )
    log(f"[i] Found {len(drafts)} Meta draft(s) in {path}.")
    return drafts
