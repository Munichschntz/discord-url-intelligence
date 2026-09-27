# Coding Assistant Rules

- Implement only the first incomplete milestone in `PLAN.md`; stop at its boundary.
- Read `SPEC.md`, `PLAN.md`, `IMPLEMENT.md`, `DOCUMENTATION.md`, `DECISIONS.md`, and `docs/API_CONTRACTS.md` before changing project behavior.
- Before integrating an external API, verify its current official documentation, record the exact contract in `docs/API_CONTRACTS.md`, and note discrepancies in `DECISIONS.md`.
- Preserve the privacy, allowlist, identity, and member-visibility invariants in `SPEC.md`. Never use a Discord user token.
- Add offline tests for changed behavior. Do not make live integration tests part of the default suite.
- Run `uv run ruff check .`, `uv run mypy src`, and `uv run pytest -q`; update `PLAN.md` and `DOCUMENTATION.md` at each completed milestone.
- Keep migrations append-only and never commit secrets, local databases, or generated private data.