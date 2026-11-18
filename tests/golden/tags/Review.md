# Review

Dated notes in `archive/`, undated reusable posts in `pool/`.
How this run went and how to rerun it: `run.log` (first lines).

## Summary

|  | count |
|---|---|
| publications read | 9 |
| unique contents | 9 |
| duplicate groups | 0 |
| drafts | 0 |
| notes written | 9 |
| decided by the local model | 0 |
| untagged | 1 |

## Decisions by the local model

None: no ambiguous join or duplicate needed the model.

## Untagged

- [[pool/post-e7d283640c80/post|Post from 2025-04-01]]

## Queries

> Requires the **Dataview** plugin (Settings -> Community plugins).

### Best of each year

The top 10%. `top_percent: N` = in the best N% (per year or over the archive,
as set by `selection.scope`).

```dataview
TABLE date, top_percent, engagement, engagement_rate, tags
FROM "archive"
WHERE top_percent <= 10
SORT year DESC, top_percent ASC
```

### What I've already covered, by program

```dataview
TABLE length(rows) AS count, max(rows.engagement) AS peak
FROM "archive"
FLATTEN tags AS tag
WHERE startswith(tag, "program/")
GROUP BY tag
SORT count DESC
```

### Content gaps

What I've covered on `apollo` without ever using the `anecdote` angle. Swap the two values to see what's missing.

```dataview
LIST
FROM "archive"
WHERE contains(tags, "program/apollo")
  AND !contains(tags, "angle/anecdote")
```

### Ready to publish

Drafts that never went out, oldest first.

```dataview
TABLE date, photo_ids, draft_ids
FROM "archive"
WHERE status = "draft"
SORT date ASC
```

### Reposts: did they work?

```dataview
TABLE times_published, published, best_engagement, top_percent
FROM "archive"
WHERE times_published > 1
SORT best_engagement DESC
```

### Strong and not posted in 12+ months

```dataview
TABLE last_published, best_engagement, times_published
FROM "archive"
WHERE top_percent <= 25
  AND last_published AND last_published <= date(today) - dur(1 year)
SORT top_percent ASC, best_engagement DESC
LIMIT 25
```

### Redundant Meta drafts

Drafts that repeat a published post or another draft (see Meta drafts above).

```dataview
TABLE status, draft_ids, last_published
FROM "archive"
WHERE length(draft_ids) > 1 OR status = "published+draft"
SORT file.name ASC
```

### Pool: best first

```dataview
TABLE content_type, format, top_percent, tags
FROM "pool"
WHERE file.name = "post"
SORT top_percent ASC
```

### Pool: untagged

```dataview
LIST
FROM "pool"
WHERE file.name = "post" AND length(tags) = 0
```

## Available axes

- **program**: `#program/apollo`, `#program/gemini`, `#program/saturn`, `#program/skylab`, `#program/voyager`
- **angle**: `#angle/anecdote`, `#angle/photo`, `#angle/video`, `#angle/quote`
