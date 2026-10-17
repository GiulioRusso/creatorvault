"""Timestamp join between export posts and insights rows."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from creatorvault.models import Post, log


def join_posts(
    posts: list[Post], insights: list[dict[str, Any]], tolerance_min: int
) -> list[dict[str, Any]]:
    """
    Matches each insights row to the closest post in time.
    Ambiguous cases are flagged, not resolved automatically.
    """
    tol = timedelta(minutes=tolerance_min)
    review: list[dict[str, Any]] = []
    used: set[str] = set()

    for rec in insights:
        candidates = [p for p in posts if abs(p.timestamp - rec["publish_time"]) <= tol]

        if not candidates:
            review.append(
                {
                    "issue": "no matching post",
                    "insights_publish_time": rec["publish_time"].isoformat(),
                    "permalink": rec["permalink"] or "",
                    "description": rec["description"][:80],
                }
            )
            continue

        if len(candidates) > 1:
            # Try to disambiguate by comparing the description, if present
            desc = (rec["description"] or "").strip().lower()
            if desc:
                scored = sorted(
                    candidates,
                    key=lambda p: _similarity(desc, p.caption.strip().lower()),
                    reverse=True,
                )
                best, second = scored[0], scored[1]
                if (
                    _similarity(desc, best.caption.lower())
                    - _similarity(desc, second.caption.lower())
                    > 0.25
                ):
                    candidates = [best]

        if len(candidates) > 1:
            review.append(
                {
                    "issue": f"{len(candidates)} posts in the same time window",
                    "insights_publish_time": rec["publish_time"].isoformat(),
                    "permalink": rec["permalink"] or "",
                    "description": rec["description"][:80],
                    "candidates": " | ".join(p.timestamp.isoformat() for p in candidates),
                }
            )
            for p in candidates:
                p.match_note = "ambiguous join: metrics not assigned, see review.csv"
            continue

        post = candidates[0]
        if post.key in used:
            review.append(
                {
                    "issue": "post already matched to another row",
                    "insights_publish_time": rec["publish_time"].isoformat(),
                    "permalink": rec["permalink"] or "",
                    "description": rec["description"][:80],
                }
            )
            continue

        post.metrics = rec["metrics"]
        post.permalink = rec["permalink"]
        used.add(post.key)

    matched = len(used)
    log(f"[i] Join: {matched}/{len(posts)} post(s) with metrics, {len(review)} row(s) to review.")
    return review


def _similarity(a: str, b: str) -> float:
    """Jaccard over words, enough to disambiguate two posts."""
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
