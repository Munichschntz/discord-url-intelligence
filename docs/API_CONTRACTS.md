# Official API Contracts

This scaffold contains no external API integration. These official references are starting points only; verify current behavior, SDK imports, versions, and required permissions when implementing each adapter, then record the exact contract used. Discord account/permission references used for Milestone 0 were checked for reachability on 2026-09-27.

| Integration | Official references | Status |
|---|---|---|
| URL extraction and normalization | [`linkify-it-py` 2.2.0 README/API](https://github.com/tsutsu3/linkify-it-py/blob/main/README.md), [`url-normalize` 2.2.1 README](https://github.com/niksite/url-normalize/blob/master/README.md) | Checked 2026-09-27 for Milestone 3 |
| `aiosqlite` and SQLite persistence | [`aiosqlite` stable API](https://aiosqlite.omnilib.dev/en/stable/api.html), [SQLite foreign keys](https://sqlite.org/foreignkeys.html), [SQLite PRAGMAs](https://sqlite.org/pragma.html), [SQLite FTS5](https://sqlite.org/fts5.html) | Checked 2026-09-27 for Milestone 2; see contract below |
| Discord Gateway, intents, messages | [Gateway events and intents](https://docs.discord.com/developers/events/gateway), [message resource](https://docs.discord.com/developers/resources/message), [discord.py API](https://discordpy.readthedocs.io/en/stable/api.html) | Checked 2026-09-27; discord.py 2.7.1 for Milestone 4 |
| Discord channel history and rate limits | [Get channel messages](https://docs.discord.com/developers/resources/channel#get-channel-messages), [rate limits](https://docs.discord.com/developers/topics/rate-limits), [discord.py channel history and raw events](https://discordpy.readthedocs.io/en/stable/api.html) | Checked 2026-09-27 for Milestone 5 |
| Discord OAuth and guild membership | [OAuth2](https://docs.discord.com/developers/topics/oauth2), [Get Current User](https://docs.discord.com/developers/resources/user#get-current-user), [Get Guild Member](https://docs.discord.com/developers/resources/guild#get-guild-member) | Setup references checked for Milestone 0; verify endpoint permissions for Milestone 10A |
| GitHub REST | [API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions), [repositories](https://docs.github.com/en/rest/repos/repos), [repository contents](https://docs.github.com/en/rest/repos/contents), [rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) | Verify for Milestone 7 |
| Hugging Face Hub | [HfApi](https://huggingface.co/docs/huggingface_hub/package_reference/hf_api), [model cards](https://huggingface.co/docs/huggingface_hub/guides/model-cards), [Hub API](https://huggingface.co/docs/hub/api/) | Verify for Milestone 8A |
| Hacker News | [Official Firebase API](https://github.com/HackerNews/API) | Verify for Milestone 8B |
| SQLite FTS5 and backup | [FTS5](https://www.sqlite.org/fts5.html), [online backup API](https://www.sqlite.org/backup.html) | Verify for Milestones 2, 9, and 16 |
| LM Studio local endpoints | [OpenAI-compatible API](https://lmstudio.ai/docs/developer/openai-compat), [structured output](https://lmstudio.ai/docs/developer/openai-compat/structured-output), [embeddings](https://lmstudio.ai/docs/developer/openai-compat/embeddings) | Verify for Milestones 12 and 13 |
| MCP Python SDK v2 | [Official SDK docs](https://py.sdk.modelcontextprotocol.io/), [SDK repository](https://github.com/modelcontextprotocol/python-sdk), [run/deployment](https://py.sdk.modelcontextprotocol.io/run/) | Verify v2 API and transport for Milestone 11 |

## Milestone 6B runtime contract (checked 2026-09-27)

- Verified with uv 0.12.7 and its official [Python installation guide](https://docs.astral.sh/uv/concepts/python-versions/)
  and [environment reference](https://docs.astral.sh/uv/reference/environment/).
  `UV_PYTHON_INSTALL_DIR` selects project-local interpreter storage. `uv python install`
  accepts `--no-bin` and `--no-registry`, preventing global command/registry registration.
  `UV_PYTHON_NO_REGISTRY=1` also disables registry discovery/registration.
- With `UV_PYTHON_PREFERENCE=only-managed`, `uv python find --system --no-project --no-python-downloads VERSION` resolves the
  downloaded interpreter. `uv venv --python PATH .venv` creates the isolated environment;
  `UV_PROJECT_ENVIRONMENT` fixes its destination. `uv sync --locked --group dev` installs
  locked dependencies there. No `pip --system`, PATH edits, or machine settings are used.
  The find-only `--system` skips virtual environments; `only-managed` still excludes
  unmanaged interpreters. This matters on repeat setup when `.venv` already exists.
- CPython's [embeddable ZIP documentation](https://docs.python.org/3/using/windows.html#the-embeddable-package)
  says normal pip dependency management is unsupported. Use uv's standalone CPython build
  for the requested private runtime plus venv. Python `-I` ignores Python environment
  variables and user-site packages at launch; the application remains installed in `.venv`.

## Milestone 5 contract

- `discord.py` 2.7.1 `Messageable.history(limit=None, after=..., oldest_first=True)` returns an async iterator and requires `READ_MESSAGE_HISTORY`. `after` resumes strictly after the given message; the collector checkpoints every successfully processed message in the same transaction as ingestion.
- `on_raw_message_edit` runs regardless of message cache state. If `cached_message` exists it represents the pre-edit message; the raw `data` payload may be partial. Use current payload content when present and fetch the current message only when required to reconstruct an uncached/partial record.
- `on_raw_message_delete` runs regardless of cache state. Persist the message's `deleted_at` marker without deleting its link rows. All reads can then exclude deleted messages while preserving audit and global link identity.
- Discord.py applies Discord REST rate-limit handling for history/fetch calls. Backfill remains sequential and uses the existing ingestion service; no separate queue or schema migration is introduced.

## Milestone 4 contract

- Discord `GUILD_MESSAGES` delivers guild `MESSAGE_CREATE` events. The `MESSAGE_CONTENT` privileged intent is required for user-entered `Message.content`; without it, content fields are generally empty. Enable this intent in the Developer Portal and request it in the Gateway connection. Discord may require privileged-intent review for larger applications.
- Use `discord.py` 2.7.1 `discord.Client` with `Intents.guilds`, `Intents.guild_messages`, and `Intents.message_content` enabled, and register `on_message` with `Client.event`. No direct REST/provider calls run in the callback.
- Locally compare the configured guild/channel snowflakes against each event before persistence. The collector ignores only its own bot user ID and does not use a user token.
- The application URL extraction and repository operations are local. Each accepted message, link occurrence, and pending enrichment job is written in one SQLite transaction; the existing partial unique index prevents duplicate outstanding enrichment jobs per link and kind.

## Milestone 3 contract

- `linkify-it-py` 2.2.0 `LinkifyIt.match()` returns match objects with `schema`, `index`, and `last_index`. Configure `fuzzy_link=False` and `fuzzy_email=False`, then accept only `http:` and `https:` schemas so extracted offsets come from the upstream parser and only explicit web URLs are indexed.
- `url-normalize` 2.2.1 `url_normalize()` provides scheme/host case normalization, IDNA handling, and default authority normalization. This application passes only the URL origin to it: its general defaults also normalize path dot segments and percent-encoded data, so the original path and query are retained separately.
- Tracking removal is intentionally local and limited to `utm_*`, `fbclid`, and `gclid`; all other query components remain in their original order and encoding. Provider host aliases and GitHub/Hugging Face/Hacker News path classification remain explicit application rules.

## Milestone 2 contract

- The official `aiosqlite` API exposes an awaitable connection factory, async connection context management, and awaitable `execute`, `commit`, `rollback`, and `close` operations. Use parameter binding for values; never interpolate user-controlled values into SQL.
- SQLite foreign-key enforcement is connection-local, so set `PRAGMA foreign_keys=ON` on every opened connection, before beginning a transaction. Set `journal_mode=WAL`, `synchronous=NORMAL`, and a nonzero `busy_timeout` at connection initialization.
- Use SQLite transactions for migration application and repository write batches. Roll back on any exception so schema changes and migration ledger rows are atomic.
- FTS5 external-content tables refer to a content table and its rowid; the application must keep the index synchronized with insert/update/delete triggers. Delete synchronization uses the FTS5 delete command with the old indexed values.
- The development runtime was checked locally with SQLite 3.45.1; creating an FTS5 table, inserting a row, and querying it with `MATCH` succeeded. FTS5 is a SQLite compile-time capability; fail initialization clearly if unavailable.

## Member website contract (Milestone 10A, checked 2026-09-27)

- Discord OAuth authorization uses `https://discord.com/oauth2/authorize` with
  `response_type=code`, scope `identify`, exact configured HTTPS callback, and random state.
  Exchange at `POST https://discord.com/api/v10/oauth2/token` using form encoding and client
  credentials; call `GET /api/v10/users/@me` with the returned Bearer token. Do not store
  access/refresh tokens. Official: https://docs.discord.com/developers/topics/oauth2 and
  https://docs.discord.com/developers/resources/user#get-current-user .
- `GET /api/v10/guilds/{guild_id}/members/{user_id}` uses bot authorization to check the
  identified user. A successful member object must identify that exact user; 404 denies
  access. Other errors fail closed when the five-minute membership cache expires. This
  single-member endpoint is distinct from List Guild Members and does not document that
  endpoint's privileged member-list intent requirement. Official:
  https://docs.discord.com/developers/resources/guild#get-guild-member .
- Before each member data response, bot-authenticated `GET /guilds/{guild_id}/roles` and
  `GET /guilds/{guild_id}/channels` provide the @everyone role permissions and channel
  overwrites. Public-to-members means @everyone has VIEW_CHANNEL (1<<10) and
  READ_MESSAGE_HISTORY (1<<16), after its overwrite, and no role/member overwrite denies
  either bit. Apply the same conservative check to a parent category. Only ordinary text
  and announcement channels (types 0 and 5) are supported; threads/forums or uncertain
  permissions are excluded. This intentionally rejects ambiguous configurations instead
  of evaluating each viewer's private-channel roles. Official:
  https://docs.discord.com/developers/resources/guild#get-guild-channels and
  https://docs.discord.com/developers/topics/permissions .
- REST errors and 429 responses never grant access. Retry-After establishes a bounded
  process-local cooldown; requests do not spin or retry in callbacks. All destinations
  are fixed Discord endpoints; shared URLs are never fetched.
- FastAPI/Jinja templates autoescape HTML; use local static CSS and server-rendered forms.
  Official template usage: https://fastapi.tiangolo.com/advanced/templates/ .
  Uvicorn listens only on loopback, trusts forwarded headers only from loopback, and has
  access logging disabled so callback query strings cannot log authorization codes.
- Tested locked versions: FastAPI 0.141.1, Starlette 1.7.0, Jinja2 3.1.6, HTTPX 0.28.1,
  and Uvicorn 0.54.0. Uvicorn settings: https://uvicorn.dev/settings/ .
- Optional trial HTTPS: `cloudflared tunnel --url http://127.0.0.1:4710` generates a random
  public hostname forwarding to the local web port. Quick Tunnels are for development and
  testing, with no uptime guarantee; use a stable tunnel for ongoing friend access.
  Official: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/ .
