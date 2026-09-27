# Milestone Plan

Status is tracked here; detailed deliverables and acceptance criteria are in `discord-intel-implementation-plan.md`.

| Milestone | Scope | Status | Main dependency additions |
|---|---|---|---|
| 0 | Discord accounts and permissions | Complete | None |
| 1 | Scaffold and freeze specification | Complete | `pydantic-settings`, `python-dotenv`; dev: `ruff`, `mypy`, `pytest` |
| 2 | SQLite and append-only migrations | Complete | `aiosqlite`; dev: `pytest-asyncio` |
| 3 | URL extraction and canonicalization | Complete | `linkify-it-py`, `url-normalize` |
| 4 | Live Discord ingestion | Complete | `discord.py` |
| 5 | Backfill, edits, and deletions | Complete | Reuse `discord.py` |
| 6 | Durable enrichment worker | Complete | None |
| 6A | Configurable cross-channel topic categories | Complete | None |
| 9 | FTS5 keyword/topic search and bounded context | Next | SQLite FTS5 |
| 10A | Member web app and first useful release | Not started | FastAPI, Jinja2 |
| 7 | GitHub metadata | Deferred beyond MVP | `httpx` |
| 8A | Hugging Face models | Deferred beyond MVP | `huggingface_hub` |
| 8B | Hacker News | Deferred beyond MVP | Reuse `httpx` |
| 8C | Generic pages and SSRF protection | Deferred beyond MVP | `httpx`, `trafilatura` |
| 10B | Optional Markdown overview | Not started | None planned |
| 11 | Optional owner-only MCP | Not started | Official MCP Python SDK v2 |
| 12 | Optional LM Studio summaries | Not started | `openai` |
| 13 | Optional embeddings and hybrid retrieval | Not started | `numpy` |
| 14 | Manual project lifecycle | Not started | None planned |
| 15 | Refresh policy | Not started | None planned |
| 16 | Operations and recovery | Not started | None planned |

Keep each milestone focused. Run the offline gates after each one, update this status and user documentation, and stop at the milestone boundary. Live integration checks stay explicitly marked and excluded from the default test suite.

## MVP scope revision (2026-09-27)

The next steps are topic categories, search over stored URLs and Discord text, then the
member website. Categories span channels and can overlap. Milestone 6A adds editable
keyword rules, Uncategorized fallback, a local preview command, and separate owner/member
category queries with offline privacy and message-lifecycle tests. It does not add the
website or search engine. Provider enrichment and milestones 10B-16 are outside this MVP.
No GitHub runners, agents, AI service, or additional infrastructure is required.
