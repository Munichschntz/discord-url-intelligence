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

## 2026-09-27: URL libraries and conservative identity

- Use `linkify-it-py` for HTTP(S) message URL matching and source offsets, and `url-normalize` for scheme, host, IDNA, and default authority normalization.
- Do not apply the normalizer to path/query data: its documented defaults normalize dot segments and percent-encoded values. Keep the raw path/query and apply only the repository's explicit root/provider and known-tracking rules.
- Retain small domain-specific rules for `www` aliases, GitHub repository identity, Hugging Face resource type, Hacker News item URLs, and tracking parameters; these are not generic URL parsing replacements.

## 2026-09-27: Discord Gateway collection

- Use `discord.py` 2.7.1 `discord.Client` with only guild, guild-message, and message-content intents for live ingestion.
- Keep the shared message ingestion service independent from Discord event objects. Gateway callbacks only apply allowlists, parse URLs, and persist message/occurrence/job rows transactionally; providers remain background work.
- Compare exact decimal string IDs for configured guild/channel allowlists and ignore only this bot's own user ID.
- No discrepancy from the current Discord Gateway or discord.py documentation was found.