---
tags:
  - index
---

# Post Archive

> Requires the **Dataview** plugin (Settings -> Community plugins).

## Best of each year

```dataview
TABLE date, engagement, engagement_rate, tags
FROM "posts"
WHERE tier = "top"
SORT year DESC, engagement DESC
```

## What I've already covered, by program

```dataview
TABLE length(rows) AS count, max(rows.engagement) AS peak
FROM "posts"
FLATTEN tags AS tag
WHERE startswith(tag, "program/")
GROUP BY tag
SORT count DESC
```

## Content gaps

What I've covered on `apollo` without ever using the `anecdote` angle. Swap the two values to see what's missing.

```dataview
LIST
FROM "posts"
WHERE contains(tags, "program/apollo")
  AND !contains(tags, "angle/anecdote")
```

## Ready to publish

Drafts that never went out, oldest first.

```dataview
TABLE date, photo_ids, draft_ids
FROM "posts"
WHERE status = "draft"
SORT date ASC
```

## Reposts: did they work?

```dataview
TABLE times_published, published, best_engagement, tier
FROM "posts"
WHERE times_published > 1
SORT best_engagement DESC
```

## Strong and not posted in 12+ months

```dataview
TABLE last_published, best_engagement, times_published
FROM "posts"
WHERE tier = "top" AND last_published AND last_published <= date(today) - dur(1 year)
SORT best_engagement DESC
LIMIT 25
```

## Redundant Meta drafts

Drafts that repeat a published post or another draft: see drafts_report.csv.

```dataview
TABLE status, draft_ids, last_published
FROM "posts"
WHERE length(draft_ids) > 1 OR status = "published+draft"
SORT file.name ASC
```

## Too many hashtags in the original

These would fail as scheduled posts: use the note's "Ready to post" caption.

```dataview
TABLE hashtags_original_count, date
FROM "posts"
WHERE contains(tags, "lint/too-many-hashtags")
SORT hashtags_original_count DESC
```

## Available axes

- **program**: `#program/apollo`, `#program/gemini`, `#program/saturn`, `#program/skylab`, `#program/voyager`
- **angle**: `#angle/anecdote`, `#angle/photo`, `#angle/video`, `#angle/quote`
