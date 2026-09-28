# Product Specification

## Purpose and scope

Discord Intel extracts URLs from approved channels in one Discord server, classifies them with simple topic rules, and makes them browsable/searchable on a small website for server friends. Collection, classification, and the member website are implemented; live website verification awaits local Discord/HTTPS configuration. No AI models, training, provider enrichment, MCP, or project tracking are planned.

The current PLAN.md supersedes the original broad roadmap. Start with simple text matching
and the existing scoped category service for website search; a separate FTS implementation
is not a prerequisite. The schema below records existing storage plus historical future
designs; it does not authorize implementing those future features. Preserve applied
migrations and existing data while simplifying the normal application path.

## Invariants

Runtime isolation: Windows setup uses the version pinned in `.python-version`, with a
private standalone interpreter in `.python` and packages in `.venv`. System-site packages
are disabled. The launcher must use this exact venv without a system-Python fallback.
Setup must not register Python globally or modify persistent PATH/system Python packages.

1. Use an authorized Discord bot, never a user token or self-bot. Ingest only configured guild and channel IDs.
2. Save every message in allowed channels, including messages without URLs. Keep the web-visible channel allowlist separate and empty by default.
3. A canonical URL has one global link row; every appearance is a separate occurrence, including repeated URLs in one message.
4. Ingestion is idempotent by Discord message ID. Edits reconcile occurrences; deletes are soft deletes. Enrichment failures never erase messages or links.
5. Gateway callbacks do local parsing and transactional persistence only. Network work runs in durable background jobs.
6. Search, metadata, and the member site work when LM Studio is offline.
7. All member routes require Discord OAuth sign-in and a current membership check. Apply web-visible filtering before ranking, snippets, counts, and detail rendering.
8. Bind the web app and owner MCP to loopback. Only expose the web app through HTTPS. Treat posted URLs as untrusted when fetching them.
9. Preserve original URL text separately from canonical identity; remove only known tracking parameters, never meaningful query parameters.
10. Store Discord IDs losslessly as decimal strings or integers, and timestamps in a consistent UTC ISO-8601 format.

## Identity and access

- Canonical link identity is URL-based: a repository and one of its issue URLs are different links.
- A Discord message is uniquely identified by its message ID; each URL occurrence has a stable occurrence index within that message.
- OAuth requests only `identify`. A short-lived `state` binds the callback to a login attempt. The bot checks the identified user against the configured guild.
- Keep only an opaque random server-side session identifier (hashed at rest), with an expiring Secure, HttpOnly, SameSite cookie. Recheck guild membership at least every five minutes and fail closed after cache expiry if Discord is unavailable.
- Web-visible channels must be in the ingestion allowlist and explicitly designated as readable by all guild members. If visibility is uncertain, exclude the channel.
- Member views include only provider metadata and live mentions/context in web-visible channels. Never expose private occurrences, owner status, manual tags, notes, internal summaries, or private-derived search rank.

## Normative schema

Migrations are ordered SQL files tracked by filename and checksum. Applied migration files are immutable. Enable foreign keys, WAL, `synchronous=NORMAL`, and a nonzero busy timeout.

| Table | Identity and required behavior |
|---|---|
| `schema_migrations` | Version primary key, filename, checksum, applied time; reject changed applied migrations. |
| `guilds` | Unique Discord guild ID, name, timestamps. |
| `channels` | Unique channel ID, guild foreign key, name/kind, `web_visible` false by default. |
| `authors` | Unique Discord author ID, display name, username, bot flag; refresh renamed display names. |
| `messages` | Unique Discord message ID; channel/author foreign keys; content, creation/edit/delete/ingest times, `has_links`. Current edited content replaces old; deleted messages do not appear in current search/context. |
| `links` | Local primary key, unique canonical URL, first original URL, host/domain, provider/resource type, metadata, first/last seen, enrichment state. Preserve the row when occurrences are deleted. |
| `message_links` | One row per occurrence with message/link foreign keys, occurrence index, raw URL, content offsets, and creation time; unique `(message_id, occurrence_index)`. |
| `link_metadata` | Link foreign key, provider, structured JSON/readable text, endpoint cache validators, fetched/checked times, content hash. Never overwrite manual fields. |
| `jobs` | Durable job identity, optional link foreign key, kind/status/availability/attempts/timestamps/error/dedupe key. Prevent duplicate outstanding work. |
| `channel_checkpoints` | Unique channel foreign key, last safely committed message ID, update time, backfill state; update with processed batch. |
| `tags`, `link_tags` | Unique tag; link/tag/source association with `manual`, `provider`, or `LLM` provenance. |
| `link_state`, `link_notes` | One lifecycle state per link and append-only notes. Added in Milestone 14. |
| `link_summaries` | Link, model, prompt version, source hash, structured JSON, generated time. Added in Milestone 12. |
| `link_embeddings` | Link, model, dimension, float32 BLOB, source hash, generated time; unique `(link_id, model)`. Added in Milestone 13. |
| `search_documents`, `search_fts` | Internal link-centric documents/index, rebuilt from current metadata and non-deleted mentions. |
| `web_search_documents`, `web_search_fts` | Separate member-safe documents built only from provider data and non-deleted web-visible mentions. Scope before ranking and snippets. |
| `web_sessions` | Hashed opaque session ID, Discord user ID, creation/expiry, last verified membership time. Added in Milestone 10A. |
| `web_login_states` | Hashed one-use OAuth state, hashed browser nonce, five-minute expiry. Added in Milestone 10A. |

Index channel/time/message for context, link/message for occurrences, job availability, and source filters. A transaction must keep message ingestion, occurrence reconciliation, job enqueue, and checkpoint updates coherent. Document and test FTS synchronization; rebuild both surfaces after relevant content or visibility changes.

## Lifecycle and search

### MVP topic categories

Categories span Discord channels. A link may belong to several topics, initially Coding,
Image Generation, Models, Tutorials, and Tools. Configurable literal keywords/phrases match
the canonical URL and current accompanying message text, case-insensitively at word
boundaries. Unmatched live links belong only to Uncategorized. Rules are not regular
expressions; punctuation separates words. Other URLs in the same message are removed
before classifying its prose. The prose applies to every link in that message.

Compute categories from current data on read for this MVP, without new tables, AI calls,
or modifying manual/provider tags. Existing links need no backfill. Edits, deletions,
visibility changes, and rule changes are reflected on the next query (restart a long-lived
service after changing its rule file). Member categories use only live occurrences in the
configured guild and channels present in both allowlists and marked web-visible in the
database. Private messages must not affect member categories, counts, or ordering.

Provider enrichment and owner/AI features are outside the product scope. Search uses stored
URLs and Discord text. Categories use literal rules; there is no trained classifier.

Status values are `NEW`, `TRY`, `WATCH`, `TESTING`, `DONE`, `BLOCKED`, and `ARCHIVED`; new links default to `NEW`. Validate every change. Manual tags and notes survive provider refresh and summary regeneration.

MVP search supports keywords and topic categories, including Uncategorized; matching a topic never depends on a provider service. Advanced filters and lifecycle status are outside scope. Default result limit is 20, hard maximum 50. Treat search input as literal text; if FTS is later justified, convert text to safe FTS terms. Result excerpts come from the current sharing message; expanded discussion context is optional and limited to three prior/following live messages in the same channel. Member-facing fields must be derived only from visible occurrences.

## Acceptance criteria

- Installation, CLI help, lint, type-check, and tests pass for the scaffold.
- One canonical URL shared in two messages yields one link and two occurrences; repeated appearances within one message remain separate.
- Replayed messages do not duplicate; edits reconcile; deletes hide content while preserving global link identity.
- Private-only links never appear on the member surface; mixed private/public links reveal only public occurrence data.
- OAuth state, session expiry, member removal, unsafe redirects, XSS-like text, oversized searches, and untrusted URL fetching are handled as specified.
