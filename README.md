# creatorvault

**Local tools for creators on Instagram and Meta: turn your exports into an Obsidian vault and a reusable content pool, turn your shop into a Meta product catalog, and shrink your videos to reel size.**

[![CI](https://img.shields.io/github/actions/workflow/status/GiulioRusso/creatorvault/ci.yml?branch=main&label=CI&logo=github)](https://github.com/GiulioRusso/creatorvault/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

| Tool | Command | From | To |
|---|---|---|---|
| [**Vault**](#vault) | `creatorvault build` | Instagram export, Meta insights, Meta drafts | Obsidian vault: dated `archive/` notes with metrics, rank and tags, an undated [content pool](#content-pool), `Review.md` and `run.log` |
| [**Catalog**](#catalog) | `creatorvault catalog` | your shop's product listing page | CSV for Meta Commerce Manager (Facebook/Instagram shop) |
| [Queue](#queue) | `creatorvault queue` | the vault's contents | images + ready captions for the next posting slots |
| [Import drafts](#import-drafts-into-an-existing-pool) | `creatorvault import-drafts` | Meta drafts | new posts added to an existing pool, without rebuilding it |
| [Compress](#compress) | `creatorvault compress` | your own videos (.mp4, .mov, .m4v) | reels at the size Meta serves back: 720x1280 H.264, ~5 MB per minute |

```mermaid
flowchart LR
    subgraph inputs["Your files"]
        IG["Instagram export ZIP"]
        INS["Meta insights CSV/XLSX"]
        DR["Meta drafts ZIP"]
        SHOP["Shop listing page"]
        VID["Your videos<br/>.mp4 / .mov"]
    end
    subgraph cmds["Commands"]
        BUILD["creatorvault build"]
        QUEUE["creatorvault queue"]
        CAT["creatorvault catalog"]
        DS["creatorvault drafts-script"]
        IMP["creatorvault import-drafts"]
        COMP["creatorvault compress"]
    end
    subgraph outs["What you get"]
        VAULT["Obsidian vault<br/>archive/ + pool/ + Review.md"]
        Q["queue/<br/>images + captions + queue.csv"]
        CSV["meta_catalog.csv"]
        SMALL[".mp4 at reel size<br/>720x1280 H.264"]
    end
    DS -. "browser script" .-> DR
    IG --> BUILD
    INS --> BUILD
    DR --> BUILD
    IG --> QUEUE
    INS --> QUEUE
    DR --> QUEUE
    BUILD --> VAULT
    QUEUE --> Q
    DR --> IMP
    IMP -. "adds new posts to pool/" .-> VAULT
    SHOP --> CAT --> CSV
    VID --> COMP --> SMALL
```

`queue` runs the same steps as `build` and then picks from the result. Everything runs on your machine: no app is connected to your account and no Meta API is called. Tagging and doubt resolution use a small model through [Ollama](https://ollama.com), locally.

## Install and configure

Python 3.11+.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[xlsx,dedup,shop]'
.venv/bin/creatorvault init          # writes config/config.yaml; refuses to overwrite
```

**The config file is the only entry point.** Every option, for every tool, lives in `config/config.yaml`; commands take nothing but `--config` (default `config/config.yaml`); `drafts-script` takes nothing at all and `compress` takes only paths:

```bash
creatorvault doctor  --config config/config.yaml   # PASS/WARN/FAIL for each input
creatorvault build   --config config/config.yaml   # vault: archive + pool
creatorvault queue   --config config/config.yaml   # next posting slots
creatorvault catalog --config config/config.yaml   # shop -> Meta catalog CSV
creatorvault drafts-script | pbcopy                # browser script: Business Suite drafts -> zip
creatorvault import-drafts --config config/config.yaml  # new drafts -> existing pool, no rebuild
creatorvault compress vault/pool                   # shrink videos to Meta reel size (needs ffmpeg)
```

Options that are unknown or were removed fail with a message naming the replacement, so a typo never silently falls back to a default. Relative paths resolve from the folder you run the command in. [config/example.yaml](config/example.yaml) is a shareable starting point; the personal `config/config.yaml` is ignored by Git. Commands below use `creatorvault` for brevity: prefix it with `.venv/bin/` or activate the environment.

---

## Vault

One note per **unique content**, even when it went out several times: media, a caption ready to repost with at most 5 hashtags, metrics, its performance rank, semantic tags and every publication.

What `creatorvault build` does, step by step (details in [How it works](#how-it-works)):

```mermaid
flowchart TD
    A["1 Read<br/>Instagram export: posts/reels + media<br/>Meta drafts"] --> B
    B["2 Join metrics<br/>insights row ↔ post by publish time"] --> C
    C["3 Rank<br/>top_percent per year or global"] --> D
    D["4 Merge reposts<br/>same photo code, image or caption"] --> F
    F["5 Keep the best<br/>selection.top_percentile"] --> G
    G["6 Tag<br/>Ollama, taxonomy labels"] --> H
    H["7 Ready caption<br/>≤ 5 hashtags"] --> W
    W["8 Write the vault"] --> P["pool/<br/>undated post.md + media"]
    W --> AR["archive/<br/>dated notes, embed pool media"]
    W --> R["Review.md + run.log"]
    B -. "unclear" .-> LM["Local model<br/>or left unassigned"]
    D -. "borderline" .-> LM2["Local model<br/>or kept separate"]
```

### What you get

```
vault/                             ← rebuilt in place (see advanced.timestamped_out)
├── Review.md                      ← start here: summary, model decisions, drafts, untagged, Dataview queries
├── run.log                        ← this run's log; first lines: date and the command to rerun it
├── archive/2024-01-26-first-line-of-the-caption.md   ← dated, metrics, publications
└── pool/first-line-of-the-caption/{post.md,01.jpg}   ← undated, see Content pool
```

Nothing else is written in the vault: no database, CSV or cache. The extracted export is temporary; the model's answers (tags, review decisions) are cached in `.creatorvault-cache/` next to the vault, so a rerun only asks about new captions. `archive/` belongs to the build: notes no longer generated are removed there. Your own notes elsewhere in the vault are never touched.

Prepared descriptions sit in fenced blocks, so their hashtags don't pollute Obsidian's tag index, and they're one click to copy. Every taxonomy axis becomes a real tag (`#topic/recipes`).

A dated note in `archive/` (frontmatter and title):

```yaml
---
date: 2024-11-20
year: 2024
time: 17:00
type: single
permalink: "https://www.instagram.com/p/XXXX/"
top_percent: 12
pool: "[[pool/our-new-autumn-menu-is-here/post]]"
status: published
times_published: 2
first_published: 2023-10-02
last_published: 2024-11-20
published: [2023-10-02, 2024-11-20]
best_engagement: 1670
engagement: 1670
engagement_rate: 6.8
reach: 24500
tags:
  - post
  - topic/recipes
  - format/photo
  - repost/yes
---

# Our new autumn menu is here
```

### Quickstart

1. Download your data ([below](#getting-your-data)) into `data/`.
2. Point the config at it:

   ```yaml
   paths:
     ig_export: data/ig-export/instagram-yourpage.zip   # or a list of ZIP parts
     insights_dir: data/insights                        # optional
     out: vault
   selection:
     metric: engagement_rate
     top_percentile: 100        # 100 = every content; 25 = only the best 25%
   ```

3. To tag captions, start Ollama and pull the model once: `ollama serve`, `ollama pull llama3.2:3b`. Without Ollama the build still runs, without tags (unless `tagging.required: true`).
4. `creatorvault build`, then open `vault/` in Obsidian (install the **Dataview** community plugin) and start from `Review.md`.

Rerun the same command after every new export: the vault is rebuilt in place. The exact command is also on the second line of `run.log`.

### Choosing what to keep: one percentile

`selection.top_percentile` is the only filter. Each publication gets `top_percent: N`, meaning it is in the best N% on `selection.metric`, ranked per calendar year (`scope: year`, so older posts from when the page was smaller aren't all at the bottom) or over the whole archive (`scope: global`). A content takes the rank of its best publication.

| `top_percentile` | Notes written |
|---|---|
| `100` (default) | every content: also posts without matching insights and never-published drafts |
| `25` | only contents ranked in the best 25%; contents without metrics are left out |

`top_percent` is `ceil(100 × (posts strictly better + 1) / posts ranked)`: the best of 4 posts is `25`, ties share the better rank. In a group of 3, the best post is `34`, so a `25` threshold keeps none of them. With no insights at all, only `100` produces notes.

### No manual review

Duplicates and ambiguous insight joins are settled automatically, so the vault holds unique posts with nothing for you to check:

- **Clear cases** follow rules: same photo code (if you set `dedup.photo_id_patterns`), same image, or caption similarity ≥ `dedup.caption_same` merge; two different photo codes never merge.
- **Borderline cases** (similarity between `caption_maybe` and `caption_same`, or several posts in an insights row's time window) go to the **local model** when `review.enabled: true`. It applies a decision only at `review.min_confidence` or above.
- **Otherwise** the conservative outcome applies: the two contents stay separate, the metrics stay unassigned. If Ollama is unavailable, the build warns and does the same (or stops, with `tagging.required: true`).

The model's decisions are listed in `Review.md` (case, reference, outcome, confidence, reason). Explicit `merge` / `split` lists in `config/dedup_overrides.yaml` always win (see [How it works](#how-it-works)).

### Getting your data

#### 1. Instagram export (required)

From `accountscenter.instagram.com`, go to **Settings → Accounts Center → Your information and permissions → Download your information → Download or transfer information**, pick the account, then choose **Some of your information → Content**.

On the final screen:

| Option | Value | Why |
|---|---|---|
| Date range | **All time** | otherwise you lose half the archive |
| Format | **JSON** | the HTML export can't be read |
| Media quality | **High** | the best resolution Instagram will give you |

Meta takes from a few hours to a couple of days, then emails you a download link (it expires after a few days). Put the ZIP, as downloaded, anywhere (e.g. `data/ig-export/`) and point `paths.ig_export` at it. There's no need to extract it.

#### Split downloads: keep the parts separate

If Instagram provides two ZIPs, keep both unchanged and list them in the same config:

```yaml
paths:
  ig_export:
    - data/ig-export/part1.zip
    - data/ig-export/part2.zip
  out: vault
```

Both ZIPs are extracted into a temporary folder that is deleted when the run ends, and post metadata and media are read across parts. Repeated metadata is imported once even with deduplication disabled. Every selected numbered `posts_1.json`, `posts_2.json`, etc., and/or `reels.json` is read. At least one part must contain metadata for a selected content type; the other parts can contain only media.

Matching uses the relative path across the ZIP parts before falling back to filenames. Identical copies are accepted; ambiguous matches with different file contents stop with an error so a post does not get the wrong photo.

#### 2. Insights export (optional)

Without insights you still get every post (with `selection.top_percentile: 100`), without metrics or ranks.

From `business.facebook.com`, go to **Insights → Content**, filter on Instagram, set the widest date range and click **Export data** (CSV or XLSX).

Use Instagram exports for the Instagram archive. Slash-separated dates are interpreted consistently per file using unambiguous dates (for example, `08/25/2026` identifies month/day order). CSV captions may contain escaped quotes and multiple lines.

Meta caps this export to a short window (usually a year). Do one export per year and put them all in one folder (e.g. `data/insights/`) with any filename. Every file there is picked up automatically, and rows duplicated across overlapping exports are dropped.

The only required column is the publish time. Several header spellings (English and Italian) are recognised. If yours isn't, rename it to `Publish time`.

> **Timezone warning.** Meta Business Suite writes publish times in **Pacific Time** (`America/Los_Angeles`), whatever your account's timezone is. A wrong `advanced.insights_tz` is the #1 cause of a near-zero match rate. An unknown timezone name is a hard error, so it can't silently shift every timestamp.

#### 3. Meta drafts (optional)

Business Suite has no export for drafts, so CreatorVault ships a small browser script that does it:

```mermaid
flowchart LR
    A["Business Suite<br/>Content → Drafts<br/>scroll to the bottom"] --> B["Chrome console<br/>paste creatorvault drafts-script"]
    B --> C["Each draft opened in a hidden frame<br/>full caption + full-size media<br/>nothing is saved"]
    C --> D["meta-drafts-YYYYMMDD-HHMM.zip"]
    D --> E["data/meta-drafts/"]
    E --> F["creatorvault build"]
```


1. In Business Suite open **Content → Posts & reels → Drafts**, set the date filter, and scroll the list to the bottom (rows only load while you scroll).
2. Copy the script: `creatorvault drafts-script | pbcopy` (macOS; elsewhere, copy what it prints).
3. Open the Chrome console (`Cmd+Option+J` / `Ctrl+Shift+J`; the first time Chrome asks you to type `allow pasting`), paste and press Enter.

It opens each loaded draft's editor in a hidden frame (nothing is saved), reads the full caption and the full-size media, and downloads one `meta-drafts-YYYYMMDD-HHMM.zip`. Put the zip, as downloaded, in `data/meta-drafts/` (`paths.meta_drafts`) and run `creatorvault build`. Settings at the top of the script: `periods` (keep only drafts created in date ranges), `limit` (e.g. `3` for a first test) and `dryRun` (list in the console, no download). The script relies on Business Suite's page structure and may need an update when Meta changes it.

The folder can hold several zips (one per period, or overlapping exports) and a hand-made `drafts.json` with the images next to it, in the same format as the one inside the zips:

```json
[
  {
    "id": "531138529578816",
    "caption": "Our new autumn menu is here ...",
    "media": ["531138529578816.jpg"],
    "updated": "2024-08-22",
    "platforms": ["facebook", "instagram"]
  }
]
```

The same draft id in more than one file counts once: the entry with the latest `updated` wins.

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Draft id from Business Suite. Entries without one are skipped. |
| `updated` | yes | Last edit, `YYYY-MM-DD` (or a full ISO timestamp). Used as the draft's date. |
| `caption` | no | Draft text. |
| `media` | no | Filenames next to `drafts.json` (or inside the same zip). A draft without an image still gets a note, without an embed. |
| `platforms` | no | Informational. |
| `content_type` | no | `posts` (default) or `reels`; used by `content_types` selection. |

Drafts go through deduplication with the published posts: a draft of a published post makes that note `status: published+draft` (a potential repost), a draft never published becomes a `status: draft` note, and several drafts of the same content become one note listing all their `draft_ids`. The **Meta drafts** table in `Review.md` has one row per draft with its note, status and `duplicate_of`: the drafts with a `duplicate_of` pointing to another draft are the redundant ones to delete in Business Suite.


#### Import drafts into an existing pool

`build` rebuilds the pool's `origin: archive` folders, which would undo edits made by hand in a pool you keep elsewhere (e.g. its own Git repo). To add only the drafts that are not there yet, point the `drafts_import` section at that pool and run:

```bash
creatorvault import-drafts --config config/config.yaml
```

```yaml
drafts_import:
  pool_posts: ../my-vault/posts/pool    # receives posts
  pool_reels: ../my-vault/reels/pool    # receives reels (omit to skip them)
  # dry_run: true                       # only the report
```

The command:
- reads every zip and `drafts.json` in `paths.meta_drafts`;
- skips a draft that repeats a post already in either pool. A repeat is the same photo code, the same image (dHash, needs Pillow) or the same caption, with the `dedup` settings `build` uses;
- writes each new content as `<pool>/<slug>/post.md` + `01.jpg`…, in the [content pool](#content-pool) format, with `origin: manual`, tags (if `tagging` is on) and at most `hashtags.max` hashtags. Several drafts of the same content become one post (the latest wins); drafts without media are skipped. Nothing already in the pool is modified, so running it again adds nothing new.
- writes `import-report.csv` in `paths.meta_drafts`, one row per draft:

| `status` | Meaning |
|---|---|
| `new` | written; `detail` is the folder. "similar to …: check it" flags a borderline caption match. |
| `duplicate of pool` | already in the pool; `detail` is the matching folder. Delete it in Business Suite or keep it as a repost. |
| `duplicate draft` | another draft of the same content was newer. |
| `skipped` | no media in the export. |


### Content pool

Every build writes `<out>/pool/`, an **undated** copy of the selected contents: a stock of posts to reuse, not a history. One folder per content, readable as plain files. The media live only here: the dated `archive/` notes embed them from the pool.

```
vault/pool/
├── our-new-autumn-menu-is-here/
│   ├── post.md
│   ├── 01.jpg
│   └── 02.jpg
└── three-tips-for-a-crispier-crust/
    ├── post.md
    └── 01.jpg
```

```markdown
---
id: 4f1c2a9be03d
origin: archive
content_type: posts
format: carousel
media: [01.jpg, 02.jpg]
top_percent: 12
tags:
  - topic/recipes
  - format/carousel
---

# Our new autumn menu is here

![](01.jpg)
![](02.jpg)

## Description

(the ready caption, in a text block: story + at most 5 hashtags)
```

There is no publication date in folder names, filenames or frontmatter; historical dates in the story stay. Folders are named after the caption's first line (`-2`, `-3` on collisions). The pool is rebuilt in place: folders with `origin: archive` belong to the build (updated, or removed when no longer selected); posts you add by hand say `origin: manual` and are never touched.

To add **new** posts by hand (or with an assistant), create a folder in the same format with `origin: manual` in the frontmatter, tags from the config's `taxonomy` and at most `hashtags.max` hashtags from `hashtags.pool`.

### Queue

**What it's for:** deciding what to post next without picking by hand. `creatorvault queue` reads your archive and prepares the next few posts, each with a date, its image and its ready caption, so you only have to upload them to Buffer or Business Suite. Nothing is published for you.

```bash
creatorvault queue --config config/config.yaml
```

```mermaid
flowchart TD
    A["Same steps as build<br/>unique, ranked, tagged contents"] --> B
    B["Candidates<br/>1. drafts never published, oldest first<br/>2. posts not out for min_repost_months, best top_percent first<br/>skip contents without an image"] --> C
    C["Order<br/>never two in a row with the same first-axis tag"] --> D
    D["Dates<br/>from start, only on days, at time"] --> E
    E["queue/<br/>NN-date-title.jpg + .txt caption<br/>queue.csv"] --> F["You upload to Buffer or Business Suite"]
```

**How it picks**, in this order:

1. **Drafts never published**, oldest first.
2. **Old posts worth reposting**: published, not out for at least `min_repost_months` (12), best `top_percent` first.
3. Never two in a row with the same value on the first taxonomy axis (e.g. not two `topic/recipes` back to back).

Contents without an image are skipped.

**When:** from `start` (default: tomorrow), only on `days`, at `time`. With `next: 3`, `days: [mon, thu]` and `start: 2026-12-01` (a Monday), the slots are Mon 1, Thu 4 and Mon 8 December at 19:30:

```
queue/
├── 01-2026-12-01-our-new-autumn-menu-is-here.jpg
├── 01-2026-12-01-our-new-autumn-menu-is-here.txt   ← ready caption, ≤ 5 hashtags
├── 02-2026-12-04-three-tips-for-a-crispier-crust.jpg
├── 02-2026-12-04-three-tips-for-a-crispier-crust.txt
├── 03-2026-12-08-....jpg
├── 03-2026-12-08-....txt
└── queue.csv                                       ← date, time, image, caption, note
```

Each run replaces the previous `queue/` files. Options are in the `queue:` section (see [the reference](#queue-1)).

### How it works

The steps of the [build diagram](#vault), in detail.

**The join.** For each insights row:

```mermaid
flowchart TD
    R["Insights row"] --> W{"Posts of the same type<br/>within tolerance_minutes?"}
    W -- "none" --> U["Metrics unassigned"]
    W -- "one" --> A["Metrics assigned"]
    W -- "several" --> C{"Row description clearly<br/>closer to one caption?"}
    C -- "yes" --> A
    C -- "no" --> M{"Local model sure?<br/>confidence ≥ min_confidence"}
    M -- "yes" --> A
    M -- "no / no model" --> U
```

The export and the insights share no ID, only a publish timestamp. Each insights row is matched to the post within `advanced.tolerance_minutes`; when several posts fall in the window, the row's description is compared with the captions. What is still ambiguous goes to the local model, which can only pick among same-type, unassigned publications within 24 hours and never invents metrics; otherwise the metrics stay unassigned.

**Deduplication.** The same content often goes out several times with a slightly different caption. Each pair of publications is decided like this:

```mermaid
flowchart TD
    P["Two publications"] --> O{"Override in<br/>dedup_overrides.yaml?"}
    O -- "merge" --> S["Same content"]
    O -- "split" --> X["Separate contents"]
    O -- "none" --> PC{"Photo codes?<br/>photo_id_patterns"}
    PC -- "same code" --> S
    PC -- "different codes" --> X
    PC -- "none" --> IM{"First images alike?<br/>dHash ≤ image_distance"}
    IM -- "yes" --> S
    IM -- "no" --> CAP{"Caption similarity"}
    CAP -- "≥ caption_same 0.85" --> S
    CAP -- "caption_maybe 0.70 to 0.85" --> M{"Local model sure?"}
    CAP -- "below 0.70" --> X
    M -- "yes, same" --> S
    M -- "no / no model" --> X
```

The three signals, strongest first:

1. **Photo code** in the caption, if you quote one (a stock, archive or catalogue ID): set the regexes in `dedup.photo_id_patterns`, e.g. `['IMG-\d{4}']`. Same code = same content, leading zeros ignored (`IMG-0042` = `IMG-42`). Two *different* codes are never merged, however similar the captions are. Off by default.
2. **Image fingerprint**: a 64-bit dHash of the first image, matched within `dedup.image_distance` bits. Needs the `dedup` extra (Pillow); without it this signal is skipped with a warning. Videos are skipped.
3. **Caption similarity**: `SequenceMatcher` ratio of the captions after dropping hashtags, mentions, URLs, emoji, punctuation and boilerplate lines (`check link in bio...`, lines of dots). ≥ `caption_same` (0.85) merges; between `caption_maybe` (0.70) and 0.85 goes to the local model, and stays separate without one. Calibrated on a real 2k-post archive, using same/different photo codes as ground truth: at 0.85 no false merge, while below 0.60 any two captions on the same topic look alike (so it's the minimum). Pairs sharing under 30% of their words are skipped, and only captions mentioning the same first year (or none) are compared, which keeps a 2k-post archive to seconds.

Optional explicit overrides in `config/dedup_overrides.yaml` take precedence over the local model and are read on every build. Each entry is a permalink, a Meta draft id, or a date/timestamp prefix (UTC, as in the note filenames):

```yaml
merge:
  - ["https://www.instagram.com/p/AAA/", "2023-05-01"]
split:
  - ["https://www.instagram.com/p/BBB/", "https://www.instagram.com/p/CCC/"]
```

The merged note is named after the **first** publication (so it doesn't move between builds) and lists every publication in a table. Its frontmatter has `times_published`, `first_published`, `last_published`, `published`, `photo_ids`, `best_engagement`, `status`, and the best publication's `top_percent` and metrics; reposts get the `repost/yes` tag.

**Hashtags.** Instagram rejects scheduled posts with too many hashtags, so every note has one **Description** block: the caption without its hashtags (inline ones become plain words, trailing `.` spacer lines go), a `.` line, then at most `hashtags.max` (≤ 5) hashtags picked by `hashtags.strategy`:

| Strategy | Hashtags used |
|---|---|
| `keep_original` (default) | the first `max` of the post's own hashtags |
| `fixed` | `hashtags.fixed` |
| `pool` | `max` unique hashtags sampled from `hashtags.pool`, ignoring the original ones; stable for the same caption |
| `taxonomy` | `hashtags.taxonomy` mapped from the post's tags (`topic/recipes: "#recipes"`), topped up with `fixed` |

**Tagging.** Captions (hashtags stripped) are sent in batches to Ollama with a prompt built from your taxonomy. For local models the request includes a JSON schema generated from the taxonomy, so the model can only answer with allowed values. Answers are then validated again, unknown values are dropped, and a malformed reply is retried once. Tags are cached by caption hash in `.creatorvault-cache/tags_cache-<settings-hash>.json` (next to the vault, never inside it), so reruns only tag new or edited captions.

### Limitations

- Model confidence is self-reported, not a calibrated probability. Photo-code conflicts and `split` overrides can't be overridden by the model.
- Image matching uses the first image only: carousels sharing an opening image can merge; use a `split` override.
- LLM tags depend on the model; small models make mistakes. Tags use the caption text, not the image.
- `content_types` reads numbered `posts_*.json` and `reels.json`; stories, archived posts and the newer `posts.json` schema are not imported.
- `archive/` belongs to the build: keep your own notes elsewhere in the vault (or in `pool/` with `origin: manual`).

---

## Compress

`creatorvault compress PATH...` shrinks your own videos to the size of the reels you download back from Meta. Phone and screen recordings are often 15-20 Mbps; Instagram re-encodes every reel to about 0.8 Mbps anyway, so a bigger file only weighs on your disk and your Git repo.

```bash
brew install ffmpeg                          # once (Linux: apt install ffmpeg)
creatorvault compress vault/pool             # every video in the folder, recursively
creatorvault compress clip.mov --bitrate 1M  # one file, higher quality
```

```mermaid
flowchart LR
    IN["PATH...<br/>files or folders"] --> F["Every .mp4 / .mov / .m4v<br/>recursively"]
    F --> E["ffmpeg two-pass<br/>720x1280 max, 30 fps max<br/>H.264 at --bitrate, AAC 64k"]
    E --> S{"Smaller than<br/>the original?"}
    S -- "no" --> K["Kept as is"]
    S -- "yes, .mp4" --> R["Replaced in place"]
    S -- "yes, .mov / .m4v" --> N["New .mp4 next to it<br/>original untouched"]
```

- Output: H.264, fits inside 720x1280 keeping the aspect ratio, at most 30 fps, AAC 64 kbps audio, two-pass encode at `--bitrate` (default `750k`).
- An `.mp4` is replaced in place. A `.mov`/`.m4v` gets a new `.mp4` next to it and is left untouched; if that `.mp4` already exists, the file is skipped.
- A video the encode would not make smaller (already small) is kept as is.
- It needs no config. Keep your originals elsewhere: replacing an `.mp4` cannot be undone.

---

## Catalog

`creatorvault catalog` turns your online shop's product listing page into a CSV in the format Meta Commerce Manager expects for a Facebook/Instagram product catalog. It needs the `shop` extra (`pip install '.[shop]'`) and the `catalog:` section of the config.

```mermaid
flowchart LR
    A["catalog.shop_url<br/>product listing page"] --> B["Every product link"]
    B --> C{"For each field"}
    C -- "1st" --> J["JSON-LD Product"]
    C -- "2nd" --> O["Open Graph tags"]
    C -- "last" --> T["Visible text"]
    J --> R["One CSV row<br/>Meta template columns"]
    O --> R
    T --> R
    R --> CSV["catalog.out<br/>meta_catalog.csv"]
```


```yaml
catalog:
  shop_url: https://example.com/shop   # required: the product listing page
  out: meta_catalog.csv
  brand: Your Brand                    # default: last path segment of shop_url
  currency: USD                        # appended to each price: "12.99 USD"
```

```bash
creatorvault catalog --config config/config.yaml
```

For each product linked from the listing it reads title, description, price, image, availability, condition and brand from **JSON-LD** (schema.org `Product`), then **Open Graph** tags, then the visible text as a last resort. A product that fails to parse is logged and skipped. Columns match Meta's template ([`doc/meta_catalog_products_template.csv`](doc/meta_catalog_products_template.csv)) exactly, and a test fails if they drift apart. Only these are filled in; the rest are written empty:

| Column | Source |
|---|---|
| `id` | product slug, from the URL |
| `title`, `description`, `image_link` | JSON-LD → Open Graph → visible text |
| `price` | formatted `"12.99 USD"` |
| `availability`, `condition` | Meta's values (`in stock`, `new`, ...) |
| `link` | the product page URL |
| `brand` | falls back to `catalog.brand`, then the shop's slug |
| `gtin`, `color`, `material`, `pattern` | JSON-LD only |

Known limitation: it hasn't been run against a real shop yet. The parsing follows patterns common to most e-commerce platforms; if a field comes out wrong, open an issue with the product page's `<script type="application/ld+json">` block.

---

## Configuration reference

### `paths`

| Key | Default | Meaning |
|---|---|---|
| `ig_export` | **required** | Instagram export: a `.zip` as downloaded, a list of ZIP parts, or an extracted folder. |
| `insights_dir` | `data/insights` | Insights files (`.csv`, `.tsv`, `.xlsx`, `.xlsm`). Missing or empty = no metrics. |
| `meta_drafts` | `data/meta-drafts` | Folder with the draft exports (`*.zip` from `creatorvault drafts-script`) and/or `drafts.json` with the draft images. Used only if it exists. |
| `out` | `vault` | Output vault. |
| `cache` | `.creatorvault-cache` next to `out` | Tag and review caches (model answers). Must be outside `out`; shared by configs in the same folder. |

### `content_types`

`[posts]` (default), `[reels]` or `[posts, reels]`. For separate post and reel vaults, use two configs that differ only in `content_types` and `paths.out` (e.g. `config/config.yaml` → `vault-posts`, `config/config-reels.yaml` → `vault-reels`) and run `build` once per config; both share `.creatorvault-cache/`. The type comes from Instagram's metadata, not the file extension: a feed video is a post. Reel notes get `content_types: [reels]` and a `reel` tag. Drafts may set `"content_type": "reels"`; untyped drafts are posts.

### `selection`

| Key | Default | Meaning |
|---|---|---|
| `metric` | `engagement_rate` | Any insights metric (`reach`, `likes`, `comments`, `shares`, `saves`, `follows`...), `engagement` (likes + comments + shares + saves, unless the export has its own column) or `engagement_rate` (engagement / reach × 100). |
| `top_percentile` | `100` | Keep contents ranked in the best N%. `100` keeps everything. |
| `scope` | `year` | `year` ranks within each calendar year; `global` over the whole archive. |

### `dedup`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` = one note per publication. |
| `caption_same` | `0.85` | Caption similarity (0–1, inclusive) that merges automatically. |
| `caption_maybe` | `0.70` | From here up to `caption_same`: the local model decides; kept separate without one. Minimum `0.60`. |
| `image_distance` | `6` | Max differing bits (of 64) between two image fingerprints. |
| `photo_id_patterns` | `[]` | Regexes for photo/catalogue codes quoted in captions (same code = same content). |
| `boilerplate` | `check link in bio`, lines of dots | Full-line regexes ignored when comparing captions. |
| `overrides` | `config/dedup_overrides.yaml` | Manual `merge` / `split` lists. |

### `tagging` and `review`

| Key | Default | Meaning |
|---|---|---|
| `tagging.enabled` | `true` | `false` skips tagging. |
| `tagging.model` | `llama3.2:3b` | Any pulled Ollama model, or a `-cloud` tag (needs `ollama signin`). Reasoning models run with thinking off; `qwen3:8b` is a good pick on a 16 GB machine (about 1–2 minutes per batch). |
| `tagging.required` | `false` | Stop when tagging or the local review can't run, instead of warning. |
| `review.enabled` | `false` (`true` in the template) | Let a local model settle borderline duplicates and joins. |
| `review.model` | `tagging.model` | Must be local: cloud models and non-loopback `OLLAMA_HOST` are rejected. |
| `review.min_confidence` | `0.85` | Below this, the conservative outcome applies. |

### `taxonomy`

Category names with their allowed labels, e.g. `topic: [recipes, travel]` → tags like `topic/recipes`. Lists allow several labels; `{values: [...], multi: false}` allows one. Changing the taxonomy or model uses a fresh tagging cache.

#### Advanced taxonomy format (optional)

The `taxonomy` block normally uses category lists, as shown in the Quickstart. To add descriptions or control multiple labels, use the mappings below inside the same YAML.

| Key | Meaning |
|---|---|
| `_instructions` | Optional prompt preamble (list of lines or one string). Keys starting with `_` are not axes. |
| any other key | One axis. Its name becomes the tag prefix (`topic/recipes`). |

Each axis:

| Field | Default | Meaning |
|---|---|---|
| `values` | **required** | Closed list of allowed values. Anything else is dropped. |
| `description` | `""` | What the axis captures, shown to the model. |
| `multi` | `false` | Whether a post can have several values on this axis. |

Changing the model or taxonomy automatically selects a fresh cache; no manual cache deletion is needed.

### `hashtags`

| Key | Default | Meaning |
|---|---|---|
| `max` | `5` | Max hashtags in the ready caption, 0 to 5. |
| `strategy` | `keep_original` | `keep_original`, `fixed`, `pool` or `taxonomy`. |
| `pool` | `[]` | Hashtags sampled by `pool` (required for that strategy). |
| `fixed` | `[]` | Used by `fixed`, and to top up `taxonomy`. |
| `taxonomy` | `{}` | Tag → hashtag map, e.g. `topic/recipes: "#recipes"`. |

### `queue`

| Key | Default | Meaning |
|---|---|---|
| `next` | `10` | How many posts to prepare. |
| `start` | tomorrow | First slot, `YYYY-MM-DD`. |
| `days` | `[mon, wed, thu, sat, sun]` | Posting days. |
| `time` | `"19:30"` | Posting time written to `queue.csv`. |
| `min_repost_months` | `12` | A published content is a repost candidate once it hasn't been out this long. |
| `out` | `queue` | Output folder. |

### `drafts_import`

Used only by `creatorvault import-drafts`, see [Import drafts](#import-drafts-into-an-existing-pool).

| Key | Default | Meaning |
|---|---|---|
| `pool_posts` | none | Pool folder that receives posts. At least one of the two pools is required. |
| `pool_reels` | none | Pool folder that receives reels; without it, reels are reported but not written. |
| `report` | `<paths.meta_drafts>/import-report.csv` | CSV with one row per draft. |
| `dry_run` | `false` | `true` writes only the report. |

### `catalog`

See [Catalog](#catalog): `shop_url` (required), `out`, `brand`, `currency`.

### `advanced` (all optional)

| Key | Default | Meaning |
|---|---|---|
| `timestamped_out` | `false` | `true` writes a new `<out>-YYYYMMDD-HHMMSS/` folder per run instead of rebuilding in place. |
| `tolerance_minutes` | `90` | Max time difference for the insights join. |
| `insights_tz` | `America/Los_Angeles` | Timezone of the insights publish times. |
| `batch_size` | `15` | Captions per Ollama call. Lower it if a model times out. |

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server address. |
| `OLLAMA_API_KEY` | unset | Bearer token, only for a cloud endpoint. |

## Privacy

- **Local Ollama (the default): nothing leaves your machine.** Exports, captions, metrics, vault and pool stay local.
- **With a `-cloud` tagging model, or a remote `OLLAMA_HOST`, captions (hashtags stripped) are sent to that server for tagging.** Metrics and media are not. The local review never uses a remote model.
- The catalog fetches your shop's public pages, and nothing else.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: `pip install -e '.[dev]'`, then `ruff check . && ruff format --check . && pytest --cov`. All test fixtures are synthetic, and a golden test keeps the vault output byte-for-byte stable (`python tests/make_golden.py` regenerates it on purpose).

## License

[MIT](LICENSE)
