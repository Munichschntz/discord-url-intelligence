# Implementation Notes

## Scaffold decisions (Milestone 1)

The scaffold uses a `src/` layout, Python 3.12+, `uv`, Pydantic Settings, and a standard-library `argparse` CLI. Settings are environment-backed and can load a local `.env`; secrets use `SecretStr`. Discord IDs remain decimal strings. The model rejects web-visible channels outside the ingestion allowlist, non-HTTPS/non-exact OAuth callback URLs, and non-loopback web/MCP bind addresses.

No Discord client, database connection, HTTP provider, worker, or web server is implemented in this milestone. `discord-intel --help` is the only CLI behavior.

## Intended boundaries

- `config.py`: validated, shared process configuration.
- `cli.py`: command registration and lightweight process entry points.
- `db/`: SQLite connection, migrations, and repositories (Milestone 2 onward).
- `urls/`: extraction and canonical identity (Milestone 3 onward).
- `ingest/`: shared message ingestion service, independent of Discord callbacks.
- `providers/`: provider adapters called by background jobs only.
- `jobs/`: durable queue and single worker.
- `search/`: separate internal and web-safe query services.
- `web/`: server-rendered member interface using only the web-safe service.
- `mcp/`: optional loopback-only owner interface.

The data flow is Discord event/backfill to the shared ingestion service, then transactional SQLite persistence and job enqueue. A durable worker enriches links and refreshes search documents. The member web app consumes only the separately scoped web-safe index.

## Validation commands

```sh
uv sync --group dev
uv run discord-intel --help
uv run ruff check .
uv run mypy src
uv run pytest -q
```