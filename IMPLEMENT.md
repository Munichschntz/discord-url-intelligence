# Implementation Notes

## Current direction

The implemented MVP path is Discord collector -> SQLite -> keyword topic rules -> member
website. `web` starts a separate loopback FastAPI/Uvicorn process, using server-rendered
Jinja templates and local CSS. The collector no longer starts an idle worker or enqueues
unused enrichment jobs. Existing rows and migration 001 are preserved. Earlier milestone
notes below are historical, not additional required features.

## Member website boundary (Milestone 10A)

`web/auth.py` stores HMAC-SHA256 digests of random session tokens and OAuth states in new
migration 002. Browser-bound login states expire in five minutes and are consumed atomically;
sessions last eight hours. `web/discord_api.py` uses fixed Discord REST destinations for
OAuth identify, exact-user guild membership, roles, and channels. No linked URL is fetched.
Membership is refreshed at least every five minutes; channel permissions before each data
request. Unknown/private/role-restricted channels, unsupported channel types, and errors
are excluded or fail closed. Do not expand the model to role-specific member views.

`web/app.py` authenticates before `TopicService.member_links/member_link`, passing the
freshly verified channel set as an additional SQL scope guard. Category/search/count/order
calculations use only those scoped current messages. Search is bounded literal text;
results paginate at 20 and details contain at most three public excerpts. No new FTS
pipeline, scraping, client JavaScript, worker service, or model dependency is involved.

Uvicorn accepts proxy headers only from loopback; the app enforces its configured HTTPS
origin. Opaque secure cookies, same-origin CSRF-checked logout, escaped templates, CSP,
no-store responses, disabled callback access logs, and bounded local rate limits protect
the member surface. One web process is the supported MVP deployment.

See `docs/WEB_SETUP.md` for configuration and controlled-guild acceptance. Offline tests
and responsive sample-page inspection are complete; live Discord setup remains pending.

## Scaffold decisions (Milestone 1)

The scaffold uses a `src/` layout, Python 3.12+, `uv`, Pydantic Settings, and a standard-library `argparse` CLI. Settings are environment-backed and can load a local `.env`; secrets use `SecretStr`. Discord IDs remain decimal strings. The model rejects web-visible channels outside the ingestion allowlist, non-HTTPS/non-exact OAuth callback URLs, and non-loopback web/MCP bind addresses.

No Discord client, database connection, HTTP provider, worker, or web server is implemented in this milestone. `discord-intel --help` is the only CLI behavior.

## SQLite boundary (Milestone 2)

`db/database.py` owns connection pragmas and ordered migration application. SQL files live in the repository `migrations/` directory and are included in built wheels; migration versions use a numeric prefix and SHA-256 checksums are stored in `schema_migrations`. A migration and its ledger record commit atomically. `db/transaction.py` provides the explicit `BEGIN IMMEDIATE` transaction boundary; repository methods accept a caller-owned connection so message, occurrence, and future job writes can share one transaction.

`db/repository.py` provides parameterized upserts for guilds, channels, authors, messages, canonical links, and individual message-link occurrences. Link rows deduplicate by canonical URL; occurrence rows deduplicate only by `(message_id, occurrence_index)`. `discord-intel db init` applies pending migrations idempotently. FTS5 tables are external-content indexes maintained by SQL triggers on their document tables.

## URL boundary (Milestone 3)

`urls/extract.py` uses `linkify-it-py` to return each explicit HTTP(S) match with its original text and half-open source offsets. `urls/canonical.py` uses `url-normalize` for scheme/authority normalization and keeps raw path/query semantics, applying only known tracking removal and provider-specific identity rules. It does not perform network access or persist data.

## Live collection boundary (Milestone 4)

`discord/collector.py` uses `discord.Client` with guild, guild-message, and message-content intents. It ignores the collector's own user ID and filters the single configured guild and source channels before calling `IngestionService`.

`ingest/service.py` accepts plain message data, independently enforces the same allowlist, extracts/canonicalizes URLs, and transactionally upserts guild, channel, author, message, link occurrences, and pending enrichment jobs. No Discord types or network provider calls enter the shared service.

`discord-intel run` initializes the configured database before connecting the bot. Live collection, backfill, and message lifecycle handling are implemented; the enrichment worker is implemented in Milestone 6 below.

## Backfill and message lifecycle (Milestone 5)

`discord-intel backfill --channel-id ID` iterates the selected allowlisted channel oldest-first using `discord.py` history. Each message and checkpoint update share the ingestion transaction; the checkpoint advances per message, including ignored bot messages, so restarts resume after the last safely handled ID.

Raw edits use current payload content when available and fetch the current message only on cache misses. Occurrences for that message are replaced transactionally. Raw deletes set the soft-delete timestamp and retain the message, occurrences, and global links for audit.

## Intended boundaries

- `config.py`: validated, shared process configuration.
- `topics.py`: literal topic rules and separate owner/member category queries.
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
## Durable enrichment worker (Milestone 6)

`jobs/worker.py` runs one worker alongside live collection. Claims use `BEGIN IMMEDIATE`, increment attempts, and commit before invoking an adapter. A five-minute adapter timeout bounds normal execution. Startup returns running jobs older than 15 minutes to pending; attempt fencing prevents an old claim from overwriting a reclaimed job.

`providers/` defines a URL/resource-type selection protocol and structured metadata result. No network adapters are registered until their respective milestones. Unsupported links remain pending without spending attempts. Successful metadata persistence, link state, job completion, and deduplicated `search_rebuild` enqueue commit together. Search rebuild jobs remain pending until Milestone 9.

Transient and unexpected adapter errors retry after 30 seconds, 2 minutes, 10 minutes, 1 hour, and 6 hours; the sixth failed attempt is terminal. Permanent failures stop immediately. Error records retain exception class names only, avoiding provider exception text that could contain secrets. Cancellation leaves the claim recoverable. The existing schema suffices; no migration was changed or added.

## Topic boundary (Milestone 6A)

`topics.py` owns validated TOML/default rules and read-time classification. Each keyword is
normalized to case-folded words; punctuation separates words. Each URL/message is matched
independently, so a phrase cannot span messages. Strip all URLs from message prose, then
classify the target canonical URL independently. This avoids another URL's hostname or slug
assigning a topic to the target. Message prose still applies to every URL in that message.

`TopicService.owner_links` and `member_links` read live evidence from existing tables in a
single scoped SQL query. DISTINCT message rows avoid counting repeated appearances twice;
the stored occurrence rows remain unchanged. Member scoping happens before classification,
counts, ordering, or pagination. No source content or unscoped link timestamps enter the
member result. The future web layer must authenticate before calling `member_links`.

`discord-intel topics` previews counts and recent links locally. `--category`, `--limit`,
and `--offset` provide bounded browsing; `--member-view` applies member data scope without
opening a server. Settings optionally point `TOPIC_RULES_PATH` to a replacement TOML file.
Rules load once per service instance. The preview scans current evidence rather than storing
derived classifications; revisit indexing if actual archive size makes this slow.

The next milestone builds keyword/topic search from URLs and Discord text, followed by
the member website. Full provider metadata is no longer a prerequisite for the MVP.

## Private runtime (Milestone 6B)

The Windows setup script uses a uv-managed standalone CPython runtime in `.python` and a
real `.venv`. Version selection is pinned in `.python-version`; dependency resolution is
locked by `uv.lock`. The script confines install/cache/environment paths to this checkout,
disables Python command/registry registration, and restores caller environment variables
and working directory on success or failure. An existing externally based environment is
moved to an ignored backup before replacement. Repeat setup compares the underlying home
directories because uv can use a stable minor-version junction for its runtime.

`run.ps1` requires a venv whose configured home is under this project's `.python`, rejects
system-site-package inclusion, and invokes its exact Python executable with `-I -m
discord_intel`. It never downloads dependencies or chooses a system interpreter. App command
arguments and exit codes are preserved; relative config/database paths use the project root.
