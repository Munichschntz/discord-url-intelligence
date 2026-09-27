# User Documentation

## Current state

The repository has completed the initial Discord account and permission setup guide in `README.md` and the Milestone 1 scaffold. Configuration validation and CLI help are available. The application does not yet connect to Discord, create a database, or run a web server.

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
```

Only `--help` is implemented during Milestone 1. Collector, worker, web, database, and MCP run modes will be introduced in their respective milestones and documented here before release.

## Validation

```sh
uv run ruff check .
uv run mypy src
uv run pytest -q
```

## Troubleshooting

- `uv: command not found`: install `uv` and ensure its executable directory is on `PATH`.
- Settings validation fails: use decimal-string Discord IDs, make the web-visible IDs a subset of source IDs, configure the exact HTTPS `/auth/callback` URL, and keep web/MCP hosts on loopback.
- The application does not collect or serve data yet: those features are later milestones, not setup failures.

Remote deployment instructions, OAuth operation, backups, and recovery will be added with the milestones that implement those features.