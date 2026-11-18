"""Performance rank: in which top N% of its year (or of the archive) a post is."""

from __future__ import annotations

import math
from collections import defaultdict

from creatorvault.models import Publication, log


def assign_ranks(posts: list[Publication], metric: str, scope: str = "year") -> None:
    """Sets p.top_percent = the smallest N such that p is in the top N% of its
    group on metric (1 = the best; ties share the better rank). Posts without
    the metric get None. scope='year' groups by calendar year, so older posts
    from when the page was smaller aren't all at the bottom."""
    groups: dict[int | None, list[Publication]] = defaultdict(list)
    for p in posts:
        p.top_percent = None
        if metric in p.metrics:
            groups[p.timestamp.year if scope == "year" else None].append(p)
    if not groups:
        log(f"[!] No post has the metric '{metric}': no ranking.")
        log(f"    Available metrics: {sorted({k for p in posts for k in p.metrics}) or 'none'}")
        return
    for group in groups.values():
        values = sorted((p.metrics[metric] for p in group), reverse=True)
        for p in group:
            better = sum(v > p.metrics[metric] for v in values)
            p.top_percent = math.ceil(100 * (better + 1) / len(values))
    log(f"[i] Ranked {sum(map(len, groups.values()))} post(s) on '{metric}' ({scope} scope).")
