# Changelog

## [Unreleased]

### Fixed
- `drafts-script`: drafts whose original image is smaller than 600 px (e.g. 500x625) no longer fail with "no media found": an image counts as media when the editor's Media panel lists its size. The editor is read only once its page has loaded.
- `drafts-script`: every draft opens in a fresh hidden frame. Reusing one frame made Business Suite ask "Leave site?"; cancelling it left the script reading the same draft (same photo) for every following one. Each read is now also checked against the draft id, the caption in the list and the previous draft's media, and fails instead of exporting a wrong copy.

### Added
- `creatorvault import-drafts` and the `drafts_import:` section: add the Meta drafts that are not in an existing pool yet, as `origin: manual` posts (tags, at most `hashtags.max` hashtags), without rebuilding or touching the pool. Repeats are found with the same dedup as `build`; `import-report.csv` lists every draft as new, duplicate of pool, duplicate draft or skipped. `dry_run: true` writes only the report.
- `creatorvault compress PATH...`: shrinks videos to Meta reel size (720x1280 H.264, two-pass at `--bitrate`, default 750k) with ffmpeg. `.mp4` files are replaced in place, other formats get a sibling `.mp4`; files already smaller are kept.
- `creatorvault drafts-script`: prints a browser script that exports Meta Business Suite drafts (full captions, full-size media) into a `meta-drafts-*.zip`. Zips dropped in `paths.meta_drafts` are read by `build`, `queue` and `doctor` next to `drafts.json`; the same draft in several files counts once (latest `updated` wins).
- Local LLM review of ambiguous insight joins and duplicate candidates, with validated decisions, caches and conservative fallbacks: nothing is left for manual review. Decisions are listed in `Review.md`.
- Undated content pool in `<out>/pool/`: one `<slug>/post.md` + media folder per selected content, with the prepared description, tags and rank, no publication dates. Hand-written pool posts (`origin: manual`) are never overwritten.
- `Review.md` (summary, model decisions, Meta drafts, untagged contents, Dataview queries) and `run.log` (with the command to rerun) in every vault.
- `selection.top_percentile` / `selection.scope` / `selection.metric`: one percentile decides which contents get a note; `100` keeps everything. Notes record `top_percent` (in the best N% of their year or archive).
- `creatorvault catalog`: the shop catalog now reads a `catalog:` config section.
- `content_types: [posts]`, `[reels]` or `[posts, reels]` to select Instagram metadata, drafts and typed insights from the same config. Reels are read from `reels.json` and labeled in vault notes.
- `hashtags.strategy: pool`: choose up to five unique hashtags from a configured topic pool, ignoring originals, with stable choices per cleaned caption.
- Split Instagram downloads: a list of ZIPs in `paths.ig_export`. Media paths are matched across parts; ambiguous files fail clearly.
- Import all numbered post JSON files and ignore repeated publication metadata across download parts.
- One-file configuration: inline YAML category lists, a concise example and a single-file `init` template.
- `tagging.required` to fail when categorization is enabled but its taxonomy or Ollama/model is unavailable.

### Fixed
- Caption similarity no longer scores unrelated captions as duplicates: the token-set component (high whenever a short caption's common words appear in a long one) is gone; plain `SequenceMatcher` with a word-overlap prefilter, defaults `caption_same: 0.85` / `caption_maybe: 0.70` (minimum 0.60), calibrated on a real archive. Dedup on 2k posts drops from ~13 minutes to seconds.
- Ollama calls send `think: false`, so reasoning models such as qwen3 are usable for tagging and review.
- Validate caption-similarity thresholds as fractions from 0 to 1 and document the 75% review/merge options.
- Keep same-time post/reel insights separate during deduplication and metric matching.
- CSV insights preserve multiline captions with escaped quotes and infer slash-date order per file from unambiguous dates.

### Changed
- Generic defaults: no photo-code patterns (`dedup.photo_id_patterns: []`), `hashtags.strategy: keep_original` with empty `fixed`/`pool`, neutral model prompts and template taxonomy. Page-specific values (e.g. NASA photo codes) now belong in your config.
- Vault layout: `archive/` (dated notes) + `pool/` (undated posts, the only copy of the media) + `Review.md` + `run.log`. No `attachments/`, `Post Archive.md`, CSV reports or manifest; caches live in `.creatorvault-cache/` outside the vault and the export is extracted to a temporary folder.
- Vault notes keep one prepared Description with up to five hashtags; the original-caption section and original-hashtag lint metadata are no longer written.
- Tag caches are separated by model and taxonomy, so edited categories no longer reuse obsolete labels.
- **The config file is the only entry point**: commands take only `--config` (default `config/config.yaml`, now required). `paths.ig_export` is required. Unknown sections, unknown `advanced` options and removed options fail with the replacement named.
- `queue` options (`next`, `start`, `days`, `time`, `out`) moved from flags to the `queue:` section.
- Performance tiers (`top`/`good`/`average`, `tier/*` tags) replaced by the numeric `top_percent` rank; index queries use it.
- Categories are configured only in the YAML file.

### Removed
- `selection: all|top`, `tiers:`, `advanced.only_top`, `advanced.tier_scope`: use `selection:`.
- `review.csv`, `dedup_review.csv` and "Needs review" callouts: ambiguous cases are resolved automatically.
- The SQLite pool and the `creatorvault pool` command; the `pool:` section (the pool is always `<out>/pool`) and `advanced.attachments_dirname`.
- CLI arguments other than `--config`: the positional export, `--out`, the queue flags, the `shop-catalog` command and its flags. The automatic discovery of the newest `instagram-*.zip`.
- Separate taxonomy files and the unused taxonomy template; use the config's `taxonomy` block.
- Unfinished browser draft exporter, its picker asset and Playwright extra. Importing local draft JSON remains supported.
- Deprecated script wrappers; use `creatorvault build` and `creatorvault shop-catalog`.
- Unreferenced logo asset.

## [0.2.0]

### Added
- Repost deduplication: publications of the same content become one note, matched on NASA photo code (different codes never merge), image dHash (`dedup` extra, Pillow) and normalized caption similarity. Borderline pairs go to `dedup_review.csv`; `config/dedup_overrides.yaml` forces `merge` / `split`.
- Notes list every publication in a table and record `times_published`, `first_published`, `last_published`, `published`, `photo_ids`, `best_engagement` and `status`; reposts get `repost/yes`. The filename comes from the first publication, so it stays put across builds.
- "Ready to post" caption with at most `hashtags.max` (5) hashtags, strategies `fixed`, `keep_original`, `taxonomy`; `hashtags_original_count` and the `lint/too-many-hashtags` tag.
- Meta Business Suite drafts as a source (`data/meta-drafts/drafts.json`): `draft` and `published+draft` statuses, `draft_ids`, `drafts_report.csv`.
- `creatorvault queue`: picks drafts and old top posts for the next slots and writes images, captions and `queue.csv`. Publishes nothing.
- Index queries: Ready to publish, Reposts, Strong and not posted in 12+ months, Redundant Meta drafts, Too many hashtags.
- `build` / `doctor` take an optional `EXPORT` argument and `--out`; `build` prints a summary table.
- `advanced.timestamped_out`.

### Changed
- **`advanced.only_top` now defaults to `false`**: every post gets a note. Set it to `true` to keep the 0.1 behaviour.
- **The vault is rebuilt in place** in `paths.out` (default `vault/`) instead of a new timestamped folder per run. Only files the previous build generated (listed in `.creatorvault-manifest.json`) are replaced or removed; notes you add are never touched. `advanced.timestamped_out: true` restores the old behaviour.
- Config is optional: `creatorvault build export.zip` works with none. `paths.insights_dir` (default `data/insights`) and the taxonomy are optional.
- Ollama unreachable or model not pulled now disables tagging with a warning instead of failing the build. `doctor` reports PASS/WARN/FAIL and exits non-zero only on FAIL.
- `Post` is now `Publication` (alias kept); notes are written from `Content` objects.
- The note's caption section is now "Original caption", next to "Ready to post".

### Migration
- Want only top posts as before? `advanced.only_top: true`.
- Scripts that looked for `<out>-YYYYMMDD-HHMMSS/`: set `advanced.timestamped_out: true`, or read `paths.out` directly.
- Dataview queries on `## Caption` or on one note per publication: reposts are now one note; use `published` / `times_published`.

## [0.1.0]

### Added
- `creatorvault` package with `init`, `doctor`, `build` and `shop-catalog` commands.
- Schema-constrained tagging: Ollama's `format` gets a JSON schema built from the taxonomy (local models), with one retry on malformed output.
- Synthetic fixtures, a byte-for-byte golden test, unit tests and CI (Python 3.11–3.13, Ubuntu and macOS).
- MIT license.

### Changed
- `scripts/ig_obsidian_archive.py` and `scripts/shop_to_meta_catalog.py` are deprecated shims around the package.
- Config and taxonomy templates now ship inside the package (`creatorvault init` copies them).
- `requirements.txt` replaced by `pyproject.toml` (extras: `xlsx`, `shop`, `dev`).

### Fixed
- An unknown `advanced.insights_tz` is now a hard error instead of a silent UTC+1 fallback that broke the join. `tzdata` is a dependency so timezones work on Windows.
