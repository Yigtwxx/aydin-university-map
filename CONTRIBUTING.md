# Contributing

Thanks for helping! Please read the [Code of Conduct](CODE_OF_CONDUCT.md) and the
[data policy](docs/data-policy.md) first. **Never commit tour data**.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/) (Python 3.12 is installed by uv),
Git. The web app (Node 24 + pnpm) arrives in a later phase.

```bash
uv sync --all-packages --all-extras   # .venv with all packages (+ pycolmap)
uvx pre-commit install      # ruff, gitleaks, repo guard on every commit
```

## Everyday commands

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pyright               # type check
uv run pytest                # tests (synthetic fixtures only)
uv run amap --help           # pipeline CLI
```

Tests that need a database or real reconstruction data are marked `db` / `recon`
and are skipped in CI: `uv run pytest -m "not db and not recon"`.

## Code style

- Code, identifiers and comments in **English**; user-facing text in TR and EN.
- Python: type hints everywhere, `ruff` (88 columns), `X | None` over `Optional`.
- Turkish text matching must use `amap_contracts.lower_tr` / `search_key`.
- Tests: one behaviour per test, named `test_<unit>_<scenario>_<expected>`,
  shared fixtures in `conftest.py`, assertion messages included.

## Commits and pull requests

- [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(pipeline): add tile sink`, `fix(api): handle unreachable route`.
  Imperative mood, subject ≤ 72 characters, body explains *why*.
- Keep PRs focused; fill in the PR template checklist.
- Architecture changes need a short ADR in `docs/adr/`.
