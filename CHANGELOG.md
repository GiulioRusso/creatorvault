# Changelog

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
