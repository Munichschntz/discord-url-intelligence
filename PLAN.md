# Milestone Plan

Status is tracked here; detailed deliverables and acceptance criteria are in `discord-intel-implementation-plan.md`.

| Milestone | Scope | Status | Main dependency additions |
|---|---|---|---|
| 0 | Discord accounts and permissions | Complete | None |
| 1 | Scaffold and freeze specification | Complete | `pydantic-settings`, `python-dotenv`; dev: `ruff`, `mypy`, `pytest` |
| 2 | SQLite and append-only migrations | Complete | `aiosqlite`; dev: `pytest-asyncio` |
| 3 | URL extraction and canonicalization | Complete | `linkify-it-py`, `url-normalize` |
| 4 | Live Discord ingestion | Complete | `discord.py` |
| 5 | Backfill, edits, and deletions | Next | Reuse `discord.py` |
| 6 | Durable enrichment worker | Not started | None planned |
| 7 | GitHub metadata | Not started | `httpx` |
| 8A | Hugging Face models | Not started | `huggingface_hub` |
| 8B | Hacker News | Not started | Reuse `httpx` |
| 8C | Generic pages and SSRF protection | Not started | `httpx`, `trafilatura` |
| 9 | FTS5 search and bounded context | Not started | SQLite FTS5 |
| 10A | Member web app and first useful release | Not started | FastAPI, Jinja2 |
| 10B | Optional Markdown overview | Not started | None planned |
| 11 | Optional owner-only MCP | Not started | Official MCP Python SDK v2 |
| 12 | Optional LM Studio summaries | Not started | `openai` |
| 13 | Optional embeddings and hybrid retrieval | Not started | `numpy` |
| 14 | Manual project lifecycle | Not started | None planned |
| 15 | Refresh policy | Not started | None planned |
| 16 | Operations and recovery | Not started | None planned |

Keep each milestone focused. Run the offline gates after each one, update this status and user documentation, and stop at the milestone boundary. Live integration checks stay explicitly marked and excluded from the default test suite.