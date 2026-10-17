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

## Worth reposting: old but strong

```dataview
TABLE year, engagement_rate, tags
FROM "posts"
WHERE tier = "top" AND year <= date(today).year - 2
SORT engagement_rate DESC
LIMIT 25
```

## Available axes

- **program**: `#program/apollo`, `#program/gemini`, `#program/saturn`, `#program/skylab`, `#program/voyager`
- **angle**: `#angle/anecdote`, `#angle/photo`, `#angle/video`, `#angle/quote`
