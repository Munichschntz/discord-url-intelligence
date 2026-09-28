# Discord Intel

Discord Intel collects URLs from selected channels in one Discord server and gives friends a searchable website with topic filters. Categories use simple keyword rules. No AI models or background enrichment services are required.

The website is implemented and tested offline. Follow the [website launch guide](docs/WEB_SETUP.md) to connect Discord sign-in and HTTPS; the first live server check is still pending.

## Requirements

- Windows PowerShell and [`uv` 0.12.7 or newer](https://docs.astral.sh/uv/getting-started/installation/)
- No system Python installation is needed; setup downloads a private runtime into this folder
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

Get the guild and channel IDs using Discord Developer Mode. The source-channel list is the ingestion allowlist. Keep `.env` private and untracked. Collection needs only the settings above. For the website, also configure OAuth, a random session secret, and an explicit `WEB_VISIBLE_CHANNEL_IDS` list using the launch guide. Leave that list empty until the owner approves channels readable by every server member.

## Install and Run

```powershell
.\setup.ps1
.\run.ps1 --help
.\run.ps1 db init
.\run.ps1 run
```

Setup pins Python via `.python-version`, stores its standalone runtime in `.python`, and
installs locked dependencies in `.venv`. It does not install packages into system Python,
register Python globally, or change PATH. Both folders and the download cache are ignored
by Git. `run.ps1` always uses this venv and needs no activation or network to launch.

If PowerShell blocks scripts, invoke just these scripts with a process-only policy:
`powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1`, then
`powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --help`.
No permanent execution-policy change is needed. First setup requires internet access.

`db init` applies local SQLite migrations. The default database path is `data/discord-intel.sqlite3`; override it with `DATABASE_PATH` in `.env` or `--database PATH` for `db init`.

`run` archives every message from the configured guild and allowed channels, including messages without URLs. It ignores the bot's own messages and records each valid HTTP(S) URL appearance. It does not start a worker or queue enrichment jobs. Stop live collection with `Ctrl+C`.

After completing website configuration, start it in a second PowerShell window:

```powershell
.\run.ps1 web
```

Open its configured HTTPS address. Friends sign in with Discord, search URLs/message text,
filter by topic, and jump back to the original Discord message. The app checks membership
and channel visibility; private mentions never contribute to results. Keep both processes
and the HTTPS tunnel running. The website never fetches shared URLs.

## Backfill and Message Changes

Backfill one configured channel with:

```powershell
.\run.ps1 backfill --channel-id 234567890123456789
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
