# Architecture Decisions

## 2026-09-27: Scaffold boundaries

- Use Python 3.12+ and `uv`; the current development container has Python 3.14, which is within that range.
- Use Pydantic Settings for validated environment configuration and `SecretStr` for secret values.
- Use `argparse` for the minimal CLI so the scaffold adds no CLI framework dependency.
- Keep `.env` and local database state out of version control. Web-visible channel IDs must be a subset of configured source channels, and web/MCP listeners default to loopback.
- No external API integration has been implemented, so no API behavior has been inferred from the reference links.

## API discrepancies

None recorded. Recheck the official contract at the milestone where each integration is first implemented.

## 2026-09-27: SQLite persistence foundation

- Use `aiosqlite` directly without an ORM. Each connection enables foreign keys, WAL, `synchronous=NORMAL`, and a nonzero busy timeout.
- Store FTS documents in ordinary content tables and synchronize FTS5 external-content indexes with SQLite triggers in the same transaction.
- Track ordered SQL migrations by version, filename, and SHA-256 checksum. Apply each migration and its ledger row atomically; never change an applied migration.
- Include the root migration directory in built wheels and use it from either a source checkout or an installed package.
- Keep Discord snowflakes as decimal text. Canonical links are unique globally while `message_links` stores each URL appearance independently.
- No discrepancy from the supplied plan or verified official docs was found.