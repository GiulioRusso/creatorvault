# Changelog

## [Unreleased] — 0.1.0

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
