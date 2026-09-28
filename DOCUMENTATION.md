# User Documentation

## Current state

The repository collects Discord URLs and categorizes them using configurable keyword rules, with support for history imports, edits, and deletions. No AI models are used. The remaining MVP work is a small website where server friends can sign in, browse topics, and search links. The website is not implemented yet. Provider enrichment, MCP, AI features, and project tracking are outside scope.

## Prerequisites

- Windows PowerShell and `uv` 0.12.7 or newer on `PATH`.
- No system Python installation is required. Setup installs the pinned standalone runtime locally.
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

```powershell
.\setup.ps1
.\run.ps1 --help
.\run.ps1 db init
.\run.ps1 run
.\run.ps1 backfill --channel-id 123456789012345678
```

`setup.ps1` downloads the standalone CPython version in `.python-version` to `.python`,
creates `.venv` with system packages excluded, and installs the locked application and
development dependencies there. The local download cache is `.uv-cache`. These folders are
ignored by Git. No system Python packages, global Python commands, registry registrations,
or persistent PATH settings are changed. Install uv using its standalone installer or
executable; it does not need to be installed with system pip.

`run.ps1` starts `.venv\Scripts\python.exe` in isolated mode and passes its arguments to
the application. It works when invoked by absolute path from another directory; configuration
and data paths still resolve relative to the project folder. No venv activation is needed.
Missing or externally based venvs produce a setup instruction rather than a system-Python
fallback. `uv run` remains usable for development checks after setup.

First setup needs internet access. Repeating setup reuses the runtime and venv; updates
install only the locked dependencies. If an existing venv uses another runtime, setup
preserves it as `.venv.previous-<unique-id>` before creating the local one. Close running
collectors before replacing their environment. A failed install can be retried with the
same command. After moving the project folder to a different location, rerun setup; venvs
are not portable. Keep the source and private `data`/`.env` files separate from disposable
runtime folders when backing up.

Python's minimal embeddable ZIP is intended for vendored application distributions and
does not support normal pip dependency management. This project uses a standalone Python
build plus a real venv to satisfy local isolation while retaining standard dependency tools.

If script execution is blocked, use a process-only invocation such as
`powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1` or
`powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 run`.

`discord-intel db init` creates the configured database parent directory, enables SQLite WAL/foreign-key settings, and applies pending append-only migrations. Override the configured database path with `--database PATH`. Repeating the command is safe; applied migration checksums are verified and modified/deleted migration files are rejected. Local database files are ignored by Git.

`discord-intel run` initializes the database, connects the authorized bot to Discord, and archives every message from the configured guild and source-channel allowlist. Valid HTTP(S) URLs become occurrence rows and pending enrichment jobs; no provider requests run in Gateway callbacks. Stop the collector with `Ctrl+C`.

`discord-intel backfill --channel-id ID` imports one allowlisted channel oldest-first. It uses the same ingestion service as live collection and commits each message together with its channel checkpoint. Re-running resumes after the last committed message. The bot needs `View Channel` and `Read Message History` in that channel.

Raw message edits update stored content and reconcile that message's URL occurrences; raw deletes set `deleted_at` while preserving links and occurrence history. No message history is fetched outside the configured guild/channel allowlist.

Before running it, configure `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, and `ALLOWED_SOURCE_CHANNEL_IDS` in the ignored local `.env`. In the Discord Developer Portal, enable Message Content Intent for the bot. Applications above Discord's privileged-intent review threshold must obtain approval. The bot needs only `View Channels` and `Read Message History` in the selected channels. Keep `WEB_VISIBLE_CHANNEL_IDS` separate; this collector does not publish message data to a website.

The web and MCP run modes are not implemented yet.

## Topic categories (Milestone 6A)

Topics group links from different channels. A link can match multiple topics. The defaults
are Coding, Image Generation, Models, Tutorials, and Tools. Links without a match appear
under Uncategorized. Classification uses each link's canonical URL and the current text of
messages sharing it. Keywords are case-insensitive whole words or phrases; punctuation
separates words, so `text-to-image` matches `text to image`. Matching is literal, not AI or
regular expressions. Other URLs in the same message are excluded from its text, but all
links in that message share its prose. These simple heuristics may misclassify ambiguous
messages; tune the rules against your actual archive.

Preview your locally collected links:

```sh
.\run.ps1 topics
.\run.ps1 topics --category "Coding"
.\run.ps1 topics --category "Uncategorized" --limit 20 --offset 0
.\run.ps1 topics --member-view
```

The command prints JSON with unique-link counts for every topic and a page of matching
links, newest mention first. Counts span the full scoped archive, even when filtering or
paging. One link can contribute to several topic counts. `message_count` counts distinct
messages, while repeated URL occurrences remain separately preserved in the database.
The default page size is 20; the maximum is 50. Category names are case-sensitive.

This is an owner-local preview, not the friends' website. By default it uses all currently
allowlisted source channels in the configured guild. `--member-view` includes only channels
also in `WEB_VISIBLE_CHANNEL_IDS` **and** explicitly marked `web_visible` in the database.
It returns no links by default. It does not grant visibility or perform Discord sign-in;
the future website will validate channel visibility and authenticate members before using
the member query service. Do not share owner output as a member-safe export.

To customize categories, copy `topics.example.toml` to `topics.toml`, edit its `[topics]`
table, and add this local setting:

```dotenv
TOPIC_RULES_PATH=topics.toml
```

For example, a complete replacement rule file can be:

```toml
[topics]
Coding = ["python", "typescript", "coding"]
"Image Generation" = ["comfyui", "stable diffusion"]
Audio = ["speech", "tts", "music"]
```

Custom files replace the defaults. Do not define Uncategorized; it is automatic. Rules
allow 1-30 uniquely named topics, each with 1-100 keywords. Missing, malformed, or invalid
files produce an error instead of silently using the defaults. Omit `TOPIC_RULES_PATH` to
restore defaults. The next CLI invocation uses the new rules; restart a long-lived service
after editing its rule file.

Existing links need no migration, reimport, or categorization job. Categories are calculated
on read from live messages, so edits, deleted mentions, and changes to channel visibility
take effect on the next query. No dependencies or external services were added. This MVP
preview scans the scoped archive; it is not yet a full-text search endpoint.

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
