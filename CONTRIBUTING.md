# Contributing

1. `python -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'`
2. Make your change on a branch; use [Conventional Commits](https://www.conventionalcommits.org/).
3. `ruff check . && ruff format . && pytest --cov` must pass (coverage ≥ 85%).
4. Fixtures must stay synthetic: never commit real exports, insights or captions.
5. Output changes are deliberate only: regenerate snapshots with
   `python tests/fixtures/make_fixtures.py` and `python tests/make_golden.py`, and explain why in the PR.
6. Open a PR against `main` describing what changed and how you tested it.
