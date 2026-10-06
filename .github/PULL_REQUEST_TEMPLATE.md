## Summary

<!-- What does this change and why? Link issues with "Closes #123". -->

## Type

- [ ] feat
- [ ] fix
- [ ] refactor
- [ ] docs
- [ ] test
- [ ] chore

## Checklist

- [ ] `uv run ruff check . && uv run ruff format --check .` passes
- [ ] `uv run pyright` and `uv run pytest` pass
- [ ] Web changes: `pnpm -r lint && pnpm -r exec tsc --noEmit && pnpm -r test` pass
- [ ] **No raw tour data, panoramas, tiles or reconstruction outputs are included** (see `docs/data-policy.md`)
- [ ] No secrets or API keys in code, configs or logs
- [ ] Docs / ADRs updated if behaviour or architecture changed
