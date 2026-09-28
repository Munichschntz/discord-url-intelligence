# Architecture Decisions

## 2026-09-27: Reduce the product to collection, classification, and a website

- The user reaffirmed that the app should only extract Discord URLs, categorize them, and
  display them to server friends. The existing keyword classifier is sufficient; no AI
  model, training, or additional classification service is needed.
- Replace the broad active roadmap with one remaining member-web milestone. Basic text
  search and topic filters ship with the page; an FTS indexing milestone is not a gate.
- Remove optional provider, AI, MCP, lifecycle, and refresh features from planned scope
  rather than describing them as inevitable later work. The old handoff is historical.
- Preserve working collection, the private runtime/venv, and existing data. Remove the idle
  enrichment worker from normal launch when implementing the website; avoid a schema
  teardown or rewrite solely to reduce code count.
- This change updates scope documentation only. Application behavior is unchanged; no
  tests were added or rerun for this documentation-only revision.

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

## 2026-09-27: Backfill and raw message lifecycle

- Reuse the shared ingestion service for live messages and sequential oldest-first backfill. Advance the existing channel checkpoint in the same transaction as each accepted message; this favors restart safety and MVP simplicity over larger uncommitted batches.
- Use raw edit/delete events so cache eviction does not lose lifecycle changes. Use raw edit content when present and fetch the current Discord message only when the payload/cache cannot provide it.
- Reconcile a message's URL occurrence rows atomically on edit. Soft-delete messages without deleting their occurrences or global link rows.
- No schema migration is needed because the initial schema already contains `channel_checkpoints` and the message deletion marker.
## 2026-09-27: Durable worker boundary

- Reuse the existing jobs schema and partial unique indexes. Atomic claims and attempt fencing support restart recovery without introducing queue infrastructure.
- Use a first-match provider registry selected by canonical URL and resource type. Leave unsupported jobs pending until a concrete adapter is implemented; do not misreport no-op enrichment as success.
- Retry adapter errors on the five planned delays, failing after six total attempts; explicitly permanent failures are terminal immediately. Bound adapter calls to five minutes and recover claims older than fifteen minutes at startup.
- Persist provider metadata and enqueue search rebuild work atomically. Search execution remains Milestone 9. No external API was integrated in Milestone 6, so no new official API contract applies.

## 2026-09-27: Topic categories and smaller MVP

- The user requested topic categories spanning channels, and a simple searchable site for
  friends without GitHub runners/agents. Insert Milestone 6A for categories and move search
  and the member website ahead of provider integrations. Provider integrations and optional
  owner/AI features are deferred beyond the MVP.
- Use configurable literal word/phrase rules, with multiple topics per link and an automatic
  Uncategorized fallback. A TOML file replaces the defaults; no dependency is needed.
- Classify current URLs and message prose on read. Avoid a category cache, new schema,
  assignment jobs, or changes to manual/provider tags until archive size warrants them.
  This makes existing data, edits, deletes, and visibility changes work without a rebuild.
- The owner preview uses current ingestion allowlists. The separate member entry point
  filters current guild, both channel allowlists, database visibility, and deleted messages
  before computing categories, counts, and last-mentioned order. Web authentication is still
  required in Milestone 10A; a local member preview does not replace it.
- No external API integration or schema change was introduced. Existing migrations remain
  unchanged. Validation: Ruff and mypy passed; all 103 offline tests passed.

## 2026-09-27: Private Python and venv

- The user requested an embedded/private runtime and a venv to keep system Python clean.
  Add setup-only Milestone 6B before search, without changing application behavior.
- Use uv's standalone CPython 3.13.13 in `.python`, and locked dependencies in `.venv`.
  The official Windows embeddable ZIP does not support ordinary pip dependency management;
  a standalone runtime supplies the requested isolation with standard venv support.
- Setup disables global executable and registry registration. Launch uses the exact local
  venv in isolated mode. No system Python install, machine configuration, new service, or
  new application dependency is required. Existing externally based venvs are preserved.
- Verified the uv CLI contract locally against 0.12.7. `python find --no-project` alone still
  discovers `.venv`; adding the find-only `--system` with `only-managed` selects the local
  base runtime. Do not combine `--managed-python` with `UV_PYTHON_PREFERENCE`, which uv rejects.
- Validation: initial local installation and an offline repeat setup succeeded; the old
  environment was preserved. All 107 offline tests, Ruff, and mypy passed with the local
  runtime. The launcher also passed an out-of-directory invocation with hostile PYTHONHOME
  and PYTHONPATH settings; its Python probe confirmed user-site packages are disabled.

## 2026-09-27: Member website and basic search (10A)

- Build one server-rendered FastAPI/Jinja website, sharing SQLite with the collector.
  Search current scoped URLs/message text and classify on read. No JS build system,
  extra FTS pipeline, provider calls, model, or worker service is needed for the MVP.
- Keep a strict public-to-all-members channel model. Fetch Discord permissions before
  each member data request; exclude any role/member read denial and uncertain parent
  category permissions. This deliberately excludes some channels Discord could resolve
  as visible through multiple roles; it never tries to publish private role-specific data.
- Add migration 002 only for hashed sessions and one-use browser-bound OAuth states.
  Keep migration 001 and all occurrence/link identities intact. Stop creating enrichment
  jobs and starting the unused worker; preserve old queue rows and modules.
- Official Discord OAuth examples use the versioned v10 token URL; use that endpoint
  with form-encoded credentials. OAuth requests identify only and stores no OAuth tokens.
  No discrepancy requiring broader API scope was found. Live permissions and tunnel
  behavior still require the controlled-guild check documented in WEB_SETUP.md.
- Keep deployment small: local bot and web processes, one HTTPS tunnel. A Quick Tunnel
  can support the initial check; its temporary hostname is not a stable hosting solution.
- Validation: 125 offline tests, Ruff, mypy, wheel build/content check, missing-config
  launcher check, and desktop/390px sample-page inspection passed. No live Discord
  credentials or HTTPS hostname were available; that acceptance check remains pending.
