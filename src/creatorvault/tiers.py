"""Performance tiers."""

from __future__ import annotations

from creatorvault.models import Post, log


def assign_tiers(posts: list[Post], metric: str, top_pct: float, scope: str = "global") -> None:
    """
    Assigns performance tiers.

    scope='global' compares all posts against each other. Fine if the page
    has been stable, but if it grew, older posts all end up at the bottom
    for reasons of age, not quality.
    scope='year' computes the thresholds separately for each calendar year:
    the 'top' tier becomes "the best of that year".
    """

    def _tier_group(group: list[Post]) -> None:
        scored = [p for p in group if p.metrics.get(metric)]
        if not scored:
            for p in group:
                p.tier = "no-data"
            return
        values = sorted((p.metrics[metric] for p in scored), reverse=True)

        def percentile_cut(pct: float) -> float:
            idx = max(0, min(len(values) - 1, int(len(values) * pct / 100) - 1))
            return values[idx]

        top_cut = percentile_cut(top_pct)
        mid_cut = percentile_cut(50)

        for p in group:
            v = p.metrics.get(metric)
            if v is None:
                p.tier = "no-data"
            elif v >= top_cut:
                p.tier = "top"
            elif v >= mid_cut:
                p.tier = "good"
            else:
                p.tier = "average"

    if not any(p.metrics.get(metric) for p in posts):
        log(f"[!] No post has the metric '{metric}': skipping tiers.")
        log(f"    Available metrics: {sorted({k for p in posts for k in p.metrics}) or 'none'}")
        return

    if scope == "year":
        by_year: dict[int, list[Post]] = {}
        for p in posts:
            by_year.setdefault(p.timestamp.year, []).append(p)
        for year, group in sorted(by_year.items()):
            _tier_group(group)
            n = sum(1 for p in group if p.tier == "top")
            log(f"[i] {year}: {n} post(s) in the top tier out of {len(group)}.")
    else:
        _tier_group(posts)
        n_top = sum(1 for p in posts if p.tier == "top")
        log(f"[i] Tiers assigned on '{metric}' (global scope): {n_top} post(s) in the top tier.")
