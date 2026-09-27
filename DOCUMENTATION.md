# User Documentation

## Current state

The repository has completed the initial Discord account and permission setup guide in `README.md`, the Python scaffold, SQLite persistence, URL extraction, live collection, and restartable backfill with message edit/delete handling. `discord-intel run` collects live messages. The application does not run a web server.

## Prerequisites

- Python 3.12 or newer.
- `uv` installed and available on `PATH`.
- For eventual collection: a Discord application/bot installed only in the intended guild, Message Content Intent enabled, and explicit source channel IDs.
- For eventual member web access: an HTTPS hostname/tunnel, a registered exact OAuth callback URI, and a separately designated web-visible channel list.

Follow the [Discord setup guide](README.md#discord-setup-milestone-0) before configuring application credentials. Never use a user token. Leave `WEB_VISIBLE_CHANNEL_IDS` empty until the server owner has confirmed public-to-members visibility.

## Local configuration

Copy `.env.example` to `.env` on the machine running the application, then replace only values that have been provisioned. Keep `.env` untracked and restrict filesystem access. Channel ID lists use JSON arrays of decimal strings, for example:

```dotenv
ALLOWED_SOURCE_CHANNEL_IDS=["123456789012345678"]
WEB_VISIBLE_CHANNEL_IDS=[]
```

Important settings include the bot token, guild ID, source and web-visible channel lists, OAuth client ID/secret/callback, web session secret, database path, optional GitHub/Hugging Face tokens, and loopback web/MCP host and ports. Settings are validated by `discord_intel.config.Settings`; invalid IDs, non-allowlisted visible channels, unsafe OAuth callbacks, and non-loopback bind hosts are rejected. Public provider content does not require GitHub or Hugging Face tokens.

## Install and commands

```sh
uv sync --group dev
uv run discord-intel --help
uv run discord-intel db init
uv run discord-intel run
uv run discord-intel backfill --channel-id 123456789012345678
```

`discord-intel db init` creates the configured database parent directory, enables SQLite WAL/foreign-key settings, and applies pending append-only migrations. Override the configured database path with `--database PATH`. Repeating the command is safe; applied migration checksums are verified and modified/deleted migration files are rejected. Local database files are ignored by Git.

`discord-intel run` initializes the database, connects the authorized bot to Discord, and archives every message from the configured guild and source-channel allowlist. Valid HTTP(S) URLs become occurrence rows and pending enrichment jobs; no provider requests run in Gateway callbacks. Stop the collector with `Ctrl+C`.

`discord-intel backfill --channel-id ID` imports one allowlisted channel oldest-first. It uses the same ingestion service as live collection and commits each message together with its channel checkpoint. Re-running resumes after the last committed message. The bot needs `View Channel` and `Read Message History` in that channel.

Raw message edits update stored content and reconcile that message's URL occurrences; raw deletes set `deleted_at` while preserving links and occurrence history. No message history is fetched outside the configured guild/channel allowlist.

Before running it, configure `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, and `ALLOWED_SOURCE_CHANNEL_IDS` in the ignored local `.env`. In the Discord Developer Portal, enable Message Content Intent for the bot. Applications above Discord's privileged-intent review threshold must obtain approval. The bot needs only `View Channels` and `Read Message History` in the selected channels. Keep `WEB_VISIBLE_CHANNEL_IDS` separate; this collector does not publish message data to a website.

The web and MCP run modes are not implemented yet.

## Validation

```sh
uv run ruff check .
uv run mypy src
uv run pytest -q
```

## Troubleshooting

- `uv: command not found`: install `uv` and ensure its executable directory is on `PATH`.
- Settings validation fails: use decimal-string Discord IDs, make the web-visible IDs a subset of source IDs, configure the exact HTTPS `/auth/callback` URL, and keep web/MCP hosts on loopback.
- Database initialization reports that FTS5 is unavailable: use a Python build whose bundled SQLite includes FTS5.
- The application collects messages but does not serve a website yet; member web access arrives in Milestone 10A.

Remote deployment instructions, OAuth operation, backups, and recovery will be added with the milestones that implement those features.
## Enrichment worker (Milestone 6)

`discord-intel run` now starts one durable worker alongside the collector. Run only one collector/worker process per database. Backfill remains a separate finite command. Stop with `Ctrl+C`; interrupted claims older than 15 minutes are recovered when the worker starts again.

Provider adapters arrive in Milestones 7-8C. Until then, collected enrichment jobs remain pending without consuming attempts or making provider requests. Successful enrichment stores metadata and queues a deduplicated search rebuild; those rebuilds will be processed starting in Milestone 9.

Transient failures retry after 30 seconds, 2 minutes, 10 minutes, 1 hour, and 6 hours, then fail after the sixth attempt. Permanent failures fail immediately. Provider calls have a five-minute timeout. Failures preserve archived messages, URL occurrences, links, and previously stored metadata. Job error fields show the exception type without potentially sensitive provider error text.
