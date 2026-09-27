# Discord Intel

Discord Intel archives messages and links from selected channels in one Discord server. The current CLI initializes the local database, collects live messages, and backfills channel history.

## Requirements

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/)
- A Discord application with a bot installed in the target server
- `View Channel` and `Read Message History` permissions for the selected channels
- **Message Content Intent** enabled in the Discord Developer Portal

Use an authorized bot only. Never use a user token or self-bot. Do not grant Administrator, message-sending, or channel-management permissions.

## Configure

Copy `.env.example` to `.env` and set:

```dotenv
DISCORD_BOT_TOKEN=your-bot-token
DISCORD_GUILD_ID=123456789012345678
ALLOWED_SOURCE_CHANNEL_IDS=["234567890123456789"]
```

Get the guild and channel IDs using Discord Developer Mode. The source-channel list is the ingestion allowlist. Keep `.env` private and untracked; never put real credentials in source files or commits. The OAuth, provider-token, and web settings in `.env.example` are not required by the current CLI. `WEB_VISIBLE_CHANNEL_IDS` is not used by a website yet and should remain empty unless explicitly configured for future use.

## Install and Run

```sh
uv sync --group dev
uv run discord-intel --help
uv run discord-intel db init
uv run discord-intel run
```

`db init` applies local SQLite migrations. The default database path is `data/discord-intel.sqlite3`; override it with `DATABASE_PATH` in `.env` or `--database PATH` for `db init`.

`run` archives every message from the configured guild and allowed channels, including messages without URLs. It ignores the bot's own messages, records each valid HTTP(S) URL appearance, and queues pending enrichment work. Provider enrichment and the website are not implemented yet, so queued jobs are not processed. Stop live collection with `Ctrl+C`.

## Backfill and Message Changes

Backfill one configured channel with:

```sh
uv run discord-intel backfill --channel-id 234567890123456789
```

History is imported oldest-first. Each message and its channel checkpoint commit together, so rerunning the command resumes after the last committed message. The bot needs `Read Message History` for that channel.

Live message edits replace that message's URL occurrences. Deletes are soft: the message is marked deleted and its links remain in the local archive. Backfill, edits, and deletes all use the same ingestion and storage rules.

## Development Checks

```sh
uv run ruff check .
uv run mypy src
uv run pytest -q
```

See [DOCUMENTATION.md](DOCUMENTATION.md) for more configuration details and troubleshooting. The full data and privacy rules are in [SPEC.md](SPEC.md).