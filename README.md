# creatorvault

**Turn your own social-media exports into a local, searchable Obsidian archive: metrics, performance tiers and local-LLM tags.**

[![CI](https://img.shields.io/github/actions/workflow/status/GiulioRusso/creatorvault/ci.yml?branch=main&label=CI&logo=github)](https://github.com/GiulioRusso/creatorvault/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

One note per content, even when it was posted several times, with its media, caption, metrics, tags, every publication and a caption ready to repost with at most 5 hashtags. Plus a Dataview index (best of each year, coverage per topic, content gaps, reposts, drafts ready to publish) and a `queue` command that prepares the next two weeks of posts. It works today with the Instagram export, Meta Business Suite insights and Meta drafts. Here is the top of a note generated from the repo's synthetic test fixtures:

```yaml
---
date: 2024-09-15
year: 2024
time: 20:00
type: single
permalink: "https://example.com/p/p3"
tier: top
status: published
times_published: 1
first_published: 2024-09-15
last_published: 2024-09-15
published: [2024-09-15]
best_engagement: 2080
hashtags_original_count: 0
engagement: 2080
engagement_rate: 10.4
reach: 20000
tags:
  - post
  - program/skylab
  - angle/anecdote
  - tier/top
---

# Countdown footage from Gemini 4
```

## Why

- **Your own data.** It reads the official exports you download from Meta. No app is connected to your account.
- **No API tokens and no scraping.** Nothing logs in as you or calls Meta's API.
- **Runs locally.** Tagging uses a small model through [Ollama](https://ollama.com) on your machine. A MacBook Air with 16 GB is plenty.

The repo also holds other small creator utilities. See [Other tools](#other-tools).

## Quickstart

```bash
pipx install 'creatorvault[xlsx,dedup] @ git+https://github.com/GiulioRusso/creatorvault.git'
creatorvault build path/to/instagram-export.zip
# open vault/ as an Obsidian vault and start from "Post Archive.md"
```

That's all you need: no config. Insights go in `data/insights/` and Meta drafts in `data/meta-drafts/`, both picked up automatically if present. Without an argument, `build` uses the newest `instagram-*.zip` in `./data/` or `./`.

To tune it, `creatorvault init` writes `config/config.yaml` and `config/taxonomy.json` (needed for tagging), and `creatorvault doctor` checks everything before a long run.

You need Python 3.11+. For tagging you also need Ollama:

```bash
ollama serve                      # keep running in another terminal
ollama pull llama3.2:3b           # default model, small and fast
```

`creatorvault doctor` prints a PASS/WARN/FAIL table and exits non-zero only on a FAIL. It checks that the export ZIP is readable and contains the posts JSON, that every insights file has a recognisable publish-time column, that the timezone is valid, that the taxonomy is valid, and (when tagging is enabled) that Ollama is reachable and the model is pulled. Missing insights, a missing taxonomy or an unreachable Ollama are only WARNs: the build still runs, without metrics or tags.

## Getting your data

### 1. Instagram export (required)

From `accountscenter.instagram.com`, go to **Settings → Accounts Center → Your information and permissions → Download your information → Download or transfer information**, pick the account, then choose **Some of your information → Content**.

On the final screen:

| Option | Value | Why |
|---|---|---|
| Date range | **All time** | otherwise you lose half the archive |
| Format | **JSON** | the HTML export can't be read |
| Media quality | **High** | the best resolution Instagram will give you |

Meta takes from a few hours to a couple of days, then emails you a download link (it expires after a few days). Put the ZIP, as downloaded, anywhere (e.g. `data/ig-export/`) and point `paths.ig_export` at it. There's no need to extract it.

> **Large accounts may get an incomplete or split export.** If your notes mostly come from one period, the ZIP is probably missing media for the rest. Look for multiple parts or a separate media-only download, and add those files into the ZIP itself. Any folder inside it works, because files are also looked up by name across the whole archive.

### 2. Insights export (optional)

Without it you still get the full archive, but without metrics or tiers.

From `business.facebook.com`, go to **Insights → Content**, filter on Instagram, set the widest date range and click **Export data** (CSV or XLSX).

Meta caps this export to a short window (usually a year). Do one export per year and put them all in one folder (e.g. `data/insights/`) with any filename. Every file there is picked up automatically, and rows duplicated across overlapping exports are dropped.

The only required column is the publish time. Several header spellings (English and Italian) are recognised. If yours isn't, rename it to `Publish time`.

> **Timezone warning.** Meta Business Suite writes publish times in **Pacific Time** (`America/Los_Angeles`), whatever your account's timezone is. A wrong `advanced.insights_tz` is the #1 cause of a near-zero match rate. An unknown timezone name is a hard error, so it can't silently shift every timestamp.

### 3. Meta drafts (optional)

Business Suite drafts are not in the Instagram export, and Business Suite can't export them. Collect them by hand (or with a browser helper) into `data/meta-drafts/drafts.json`, with the images in the same folder:

```json
[
  {
    "id": "531138529578816",
    "caption": "Jul. 20, 1969: ...",
    "media": ["531138529578816.jpg"],
    "updated": "2024-08-22",
    "platforms": ["facebook", "instagram"]
  }
]
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Draft id from Business Suite. Entries without one are skipped. |
| `updated` | yes | Last edit, `YYYY-MM-DD` (or a full ISO timestamp). Used as the draft's date. |
| `caption` | no | Draft text. |
| `media` | no | Filenames next to `drafts.json`. A draft without an image still gets a note, without an embed. |
| `platforms` | no | Informational. |

Drafts go through deduplication with the published posts: a draft of a published post makes that note `status: published+draft` (a potential repost), a draft never published becomes a `status: draft` note, and several drafts of the same content become one note listing all their `draft_ids`. `drafts_report.csv` has one row per draft with its note, status and `duplicate_of`: the drafts with a `duplicate_of` pointing to another draft are the redundant ones to delete in Business Suite.

## How it works

```mermaid
flowchart LR
    subgraph Inputs
        A["Instagram export (.zip)\nimages + captions + timestamp"]
        B["Meta Business Suite insights\n(.csv / .xlsx, one per year)"]
        C["config/taxonomy.json\ntagging axes + values"]
        D["config/config.yaml\npaths, tiers, tagging, advanced"]
    end

    A --> E["Parse export\nposts + media + captions"]
    B --> F["Parse insights\nmetrics per row"]
    E --> G["Timestamp join\n(± tolerance_minutes)"]
    F --> G
    G -->|ambiguous match| H["review.csv"]
    G -->|matched| I["Performance tiers\ntop/good/average per year"]
    P["Meta drafts\n(drafts.json, optional)"] --> Q
    I --> Q["Dedup reposts\nphoto code, image, caption"]
    Q -->|borderline pairs| R["dedup_review.csv"]
    C --> M["Semantic tagging\nvia Ollama (local/cloud)"]
    Q --> M
    M --> S["Ready caption\n≤ 5 hashtags"]
    S --> N["Write Obsidian notes\nposts/ + attachments/"]
    N --> O["Post Archive.md\nDataview index"]
    S --> T["creatorvault queue\nqueue/"]

    D -.config.-> G
    D -.config.-> I
    D -.config.-> Q
    D -.config.-> M
```

**The join.** The export and the insights share no ID, only a publish timestamp. Each insights row is matched to the post within `tolerance_minutes`. When several posts fall in the window, the row's description is compared with the captions. If that doesn't clearly pick one, nothing is guessed: the row goes to `review.csv` and the affected notes get a warning callout.

**Tiers.** Posts are ranked on `tiers.metric`, by default within each calendar year, so older posts from when the page was smaller aren't all at the bottom. The best `top_percentile`% become `top`, the rest of the top half `good`, the others `average`. Posts with no matching insights row get `no-data`. Tiers are computed per publication; a content posted several times takes its best one.

**Deduplication.** The same content often goes out several times with a slightly different caption. Publications are grouped with three signals, strongest first:

1. **NASA photo code** in the caption (`AS11-40-5903`, `S69-31739`, `GT4-...`, `STS...`, `ISS...-E-...`; the regexes are configurable). Same code = same content, zero-padding ignored (`AS14-66-09302` = `AS14-66-9302`). Two *different* codes are never merged, however similar the captions are.
2. **Image fingerprint**: a 64-bit dHash of the first image, matched within `dedup.image_distance` bits. Needs the `dedup` extra (Pillow); without it this signal is skipped with a warning. Videos are skipped.
3. **Caption similarity** after dropping hashtags, mentions, URLs, emoji, punctuation and boilerplate lines (`check link in bio...`, lines of dots): ≥ `caption_same` (0.90) merges, between `caption_maybe` (0.75) and 0.90 is **not** merged but written to `dedup_review.csv`. Only captions mentioning the same first year (or none) are compared, so big archives don't need every pair.

Decide on the review rows in `config/dedup_overrides.yaml`, read on every build. Each entry is a permalink, a Meta draft id, or a date/timestamp prefix (UTC, as in the note filenames):

```yaml
merge:
  - ["https://www.instagram.com/p/AAA/", "2023-05-01"]
split:
  - ["https://www.instagram.com/p/BBB/", "https://www.instagram.com/p/CCC/"]
```

The merged note is named after the **first** publication (so it doesn't move between builds) and lists every publication in a table. Its frontmatter has `times_published`, `first_published`, `last_published`, `published`, `photo_ids`, `best_engagement`, `status`, and the best publication's `tier` and metrics; reposts get the `repost/yes` tag.

**Hashtags.** Instagram doesn't publish scheduled or API posts with more than 5 hashtags. Every note has a **Ready to post** block: the caption without its hashtags (inline ones become plain words, trailing `.` spacer lines go), a `.` line, then at most `hashtags.max` hashtags picked by `hashtags.strategy`:

| Strategy | Hashtags used |
|---|---|
| `fixed` (default) | `hashtags.fixed` |
| `keep_original` | the first `max` of the post's own hashtags |
| `taxonomy` | `hashtags.taxonomy` mapped from the post's tags (`program/apollo: "#apollo"`), topped up with `fixed` |

Notes whose original caption had more than `max` get `lint/too-many-hashtags`, with the count in `hashtags_original_count`.

**Tagging.** Captions (hashtags stripped) are sent in batches to Ollama with a prompt built from your taxonomy. For local models the request includes a JSON schema generated from the taxonomy, so the model can only answer with allowed values. Answers are then validated again, unknown values are dropped, and a malformed reply is retried once. Tags are cached by caption hash in `<out>/.ig_archive_cache/tags_cache.json`, so reruns only tag new or edited captions.

**Limitations, honestly.**
- The join is timestamp-based. Posts published minutes apart can be ambiguous; check `review.csv`.
- Dedup can't see that two different photos tell the same story, and a heavily rewritten caption may land in `dedup_review.csv` rather than merge. Overrides fix both.
- LLM tags depend on the model. Small models make mistakes; tighten `_instructions` or the value list if one keeps happening.
- The export is a snapshot. To pick up new posts, download again and rerun.

## Configuration reference

`creatorvault init` copies the commented templates. Paths are relative to the folder you run `creatorvault` from, or absolute.

### Commands

| Command | Does |
|---|---|
| `creatorvault init [--dir config]` | Copies `config.yaml` and `taxonomy.json` templates. Refuses to overwrite. |
| `creatorvault doctor [EXPORT] [--config PATH] [--out DIR]` | Checks config, export, insights, timezone, taxonomy and Ollama. |
| `creatorvault build [EXPORT] [--config PATH] [--out DIR]` | Builds the vault. Config is optional (default `config/config.yaml` if it exists). Without `EXPORT` and `paths.ig_export`, the newest `instagram-*.zip` in `./data/` or `./` is used. |
| `creatorvault queue [EXPORT] [--next 10] [--days mon,wed,...] [--time 19:30] [--start YYYY-MM-DD] [--out queue/]` | Prepares the next posts: see [Queue](#queue). |
| `creatorvault shop-catalog URL [...]` | See [Other tools](#other-tools). |

### `paths`

| Key | Default | Meaning |
|---|---|---|
| `ig_export` | `EXPORT` argument, else newest `instagram-*.zip` in `./data/` or `./` | Instagram export: a `.zip` as downloaded, or an extracted folder. |
| `insights_dir` | `data/insights` | Folder with the insights files (`.csv`, `.tsv`, `.xlsx`, `.xlsm`). Missing or empty = archive without metrics. |
| `out` | `vault` | Output vault (`--out` overrides it). |
| `cache` | `<out>/.ig_archive_cache` | Extracted export and tag cache, reused across runs. |
| `taxonomy` | `config/taxonomy.json` | Taxonomy used for tagging. Missing = no tags. |
| `meta_drafts` | `data/meta-drafts` | Folder with `drafts.json` and the draft images. Used only if it exists. |

### `tiers`

| Key | Default | Meaning |
|---|---|---|
| `metric` | `engagement` | Any insights metric (`reach`, `impressions`, `likes`, `comments`, `shares`, `saves`, `follows`), `engagement` (likes + comments + shares + saves, unless the export has its own column) or `engagement_rate` (engagement / reach × 100, independent of page growth). |
| `top_percentile` | `25` | Share of posts in the `top` tier, per scope. |

### `tagging`

| Key | Default | Meaning |
|---|---|---|
| `model` | `llama3.2:3b` | Any pulled Ollama model, or a `-cloud` tag (needs `ollama signin`). Prefer non-reasoning models: reasoning ones (`qwen3`, `deepseek-r1`) are much slower here and can time out. |
| `enabled` | `true` | `false` skips tagging (no Ollama needed). |

### `dedup`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` = one note per publication, as in 0.1. |
| `image_distance` | `6` | Max differing bits (of 64) between two image fingerprints. |
| `caption_same` | `0.90` | Caption similarity that merges. |
| `caption_maybe` | `0.75` | Caption similarity that goes to `dedup_review.csv`. |
| `photo_id_patterns` | NASA codes (see template) | Regexes for photo codes. |
| `boilerplate` | `check link in bio`, lines of dots | Full-line regexes ignored when comparing captions. |
| `overrides` | `config/dedup_overrides.yaml` | Manual `merge` / `split` lists. |

### `hashtags`

| Key | Default | Meaning |
|---|---|---|
| `max` | `5` | Max hashtags in the ready caption. |
| `strategy` | `fixed` | `fixed`, `keep_original` or `taxonomy` (see [How it works](#how-it-works)). |
| `fixed` | `#history #space #moon #exploration #science` | Used by `fixed`, and to top up `taxonomy`. |
| `taxonomy` | `{}` | Tag → hashtag map, e.g. `program/apollo: "#apollo"`. |

### `queue`

| Key | Default | Meaning |
|---|---|---|
| `days` | `[mon, wed, thu, sat, sun]` | Posting days (`--days` overrides). |
| `time` | `"19:30"` | Posting time written to `queue.csv` (`--time` overrides). |
| `min_repost_months` | `12` | A top post is a repost candidate once it hasn't been out for this long. |

### `advanced` (all optional)

| Key | Default | Meaning |
|---|---|---|
| `only_top` | `false` | Only write notes for `top` posts. Note that years without insights have no `top` posts. |
| `timestamped_out` | `false` | `false` writes into `out` every time, replacing only the files the previous build generated (tracked in `.creatorvault-manifest.json`): notes you add to the vault are never touched. `true` writes a new `<out>-YYYYMMDD-HHMMSS/` folder per run. |
| `tolerance_minutes` | `90` | Max time difference for the join. |
| `insights_tz` | `America/Los_Angeles` | Timezone of the insights publish times (see the warning above). |
| `tier_scope` | `year` | `year` ranks within each calendar year; `global` ranks all posts together. |
| `attachments_dirname` | `attachments` | Media folder inside the vault. |
| `batch_size` | `15` | Captions per Ollama call. Lower it if a model times out. |

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server address. |
| `OLLAMA_API_KEY` | unset | Sent as a Bearer token, only for talking to a cloud endpoint directly. |

### `taxonomy.json`

| Key | Meaning |
|---|---|
| `_instructions` | Optional prompt preamble (list of lines or one string). Keys starting with `_` are not axes. |
| any other key | One axis. Its name becomes the tag prefix (`program/apollo`). |

Each axis:

| Field | Default | Meaning |
|---|---|---|
| `values` | **required** | Closed list of allowed values. Anything else is dropped. |
| `description` | `""` | What the axis captures, shown to the model. |
| `multi` | `false` | Whether a post can have several values on this axis. |

After changing values, delete `tags_cache.json` to re-tag already-tagged posts.

## Output

```
vault/                             ← rebuilt in place (see timestamped_out)
├── Post Archive.md                ← Dataview index, start here
├── posts/2024-01-26-first-line-of-the-caption.md
├── attachments/2024-01-26-first-line-of-the-caption.jpg
├── review.csv                     ← only if the join left ambiguous rows
├── dedup_review.csv               ← only if some reposts are borderline
└── drafts_report.csv              ← only with Meta drafts
```

The index has queries for the best of each year, coverage per taxonomy value, content gaps, drafts ready to publish, reposts and how they did, strong posts not out in 12+ months, redundant Meta drafts and captions with too many hashtags.

## Queue

Every two weeks or so:

```bash
creatorvault queue --next 10 --start 2026-11-30
```

It runs the same pipeline as `build` (using the caches), then picks never-published drafts first (oldest first), then `tier: top` contents not published for `queue.min_repost_months` (best engagement first), avoiding two in a row with the same value on the first taxonomy axis. Contents without an image are skipped. Slots follow `--days` and `--time` (default from `queue:`), starting at `--start` (default: tomorrow).

It writes into `queue/`, replacing the previous queue's files:

```
queue/
├── 01-2026-11-30-first-line-of-the-caption.jpg
├── 01-2026-11-30-first-line-of-the-caption.txt   ← ready caption, ≤ 5 hashtags
├── ...
└── queue.csv                                      ← date, time, image, caption, note
```

Nothing is published and no API is called: upload the files to Buffer or Business Suite yourself.

Open the folder as a vault in Obsidian, install the **Dataview** community plugin, and open `Post Archive.md`. Captions sit in fenced blocks so their hashtags don't pollute Obsidian's tag index, and they're one click to copy for reposting. Every taxonomy axis becomes a real tag (`#program/apollo`).

## Privacy

- **Local Ollama (the default): nothing leaves your machine.** The exports, captions, metrics and the vault all stay local.
- **With a `-cloud` model, or `OLLAMA_HOST` pointed at a remote server, your captions (hashtags stripped) are sent to that server for tagging**, along with the taxonomy prompt. Metrics, media and the export itself are not sent.
- With `tagging.enabled: false`, nothing touches the network at all.

## Roadmap

- More sources behind a common `Source` interface: Facebook Page, TikTok, YouTube Takeout.

## Other tools

### Shop → Meta Commerce Manager catalog

`creatorvault shop-catalog` turns your online shop's product listing page into a CSV in the format Meta Commerce Manager expects for a Facebook/Instagram product catalog. It needs the `shop` extra:

```bash
pip install -e '.[shop]'
creatorvault shop-catalog https://app.amazecommerce.com/shop/spaceisvintage --out catalog.csv
```

| Flag | Default | Meaning |
|---|---|---|
| `shop_url` | **required** | URL of the shop's product listing page |
| `--out PATH` | `./meta_catalog.csv` | Output CSV path |
| `--brand NAME` | last path segment of `shop_url` | Used when a product page doesn't declare its own brand |
| `--currency CODE` | `USD` | ISO currency code appended to each price (`"12.99 USD"`) |

For each product linked from the listing it reads title, description, price, image, availability, condition and brand from **JSON-LD** (schema.org `Product`), then **Open Graph** tags, then the visible text as a last resort. A product that fails to parse is logged and skipped. Columns match Meta's template ([`doc/meta_catalog_products_template.csv`](doc/meta_catalog_products_template.csv)) exactly, and a test fails if they drift apart. Only these are filled in; the rest are written empty:

| Column | Source |
|---|---|
| `id` | product slug, from the URL |
| `title`, `description`, `image_link` | JSON-LD → Open Graph → visible text |
| `price` | formatted `"12.99 USD"` |
| `availability`, `condition` | Meta's values (`in stock`, `new`, ...) |
| `link` | the product page URL |
| `brand` | falls back to `--brand`, then the shop's slug |
| `gtin`, `color`, `material`, `pattern` | JSON-LD only |

Known limitation: it hasn't been run against a real shop yet. The parsing follows patterns common to most e-commerce platforms; if a field comes out wrong, open an issue with the product page's `<script type="application/ld+json">` block.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: clone, `pip install -e '.[dev]'`, then `ruff check . && pytest --cov`. All test fixtures are synthetic, and a golden test keeps the vault output byte-for-byte stable.

## License

[MIT](LICENSE)
