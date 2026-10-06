# Contributing

Thanks for helping! Please read the [Code of Conduct](CODE_OF_CONDUCT.md) and the
[data policy](docs/data-policy.md) first. **Never commit tour data**.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/) (Python 3.12 is installed by uv),
Node 24+ with pnpm (`corepack enable`), Git.

```bash
uv sync --all-packages --all-extras   # .venv with all packages (+ pycolmap)
pnpm install
uvx pre-commit install      # ruff, gitleaks, repo guard on every commit
cp .env.example .env        # fill in what you need (see below)
./start.sh                  # run API + web locally
```

Nothing in `.env` is required to run the map locally. The comments in
`.env.example` say where each value comes from:

- `GROQ_API_KEY`, `GEMINI_API_KEY`: the assistant. Without them it is off.
  `AMAP_ASSISTANT_MODEL=offline` gives a deterministic stand-in model, as in
  the E2E tests.
- `NEXT_PUBLIC_CESIUM_ION_TOKEN`: Google Photorealistic 3D Tiles for the
  landing dive and the map's photoreal view. Without it the dive uses the
  satellite imagery from `amap export earth`.
- `DATABASE_POOLER_URL`, `AMAP_API_DATABASE_URL`: Supabase. The API also runs
  from the in-memory graph without them.
- `COLMAP_BIN`, `OPENMVS_BIN`, `GLTFPACK_BIN`: only for the reconstruction
  pipeline (`docs/reconstruction.md`).

## Everyday commands

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pyright               # type check
uv run pytest                # tests (synthetic fixtures only)
uv run amap --help           # pipeline CLI
pnpm --filter web lint       # web: eslint
pnpm --filter web typecheck  # web: tsc --noEmit
pnpm --filter web test       # web: vitest
pnpm --filter web test:e2e   # web: Playwright + axe (starts its own API and web)
pnpm format                  # prettier (web + config files)
uv run python -m amap_api.export_openapi && pnpm --filter web gen:api  # after API changes
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
