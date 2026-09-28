# MVP Plan

## Product

Collect URLs from approved Discord channels, classify them into topics, and let server
friends browse and search them on one small website. No AI models or training are needed.

## Work remaining

| Milestone | Scope | Status |
|---|---|---|
| Collection | Bot, URL extraction, deduplication, backfill, edits/deletes, SQLite | Complete |
| Classification | Configurable keyword/URL rules, overlapping topics, Uncategorized | Complete |
| Local runtime | Private Python and isolated venv | Complete |
| Member web app (10A, including basic search) | Discord sign-in, topic filters, keyword search, recent links, original-message links, HTTPS setup | Next |

Implement only the first incomplete milestone and stop at its boundary. There is no
separate search-platform milestone before the website. Start with the existing scoped
category service and simple text matching against URLs and current message text. Add an
index only if measured archive size makes it necessary.

## Website acceptance

- A friend signs in with Discord and can browse all approved shared links in one place.
- Topic filters combine with a search box; unmatched links remain under Uncategorized.
- Results show the URL, topics, source channel, short message excerpt, and original-message link.
- Results have bounded pagination (20 by default, at most 50) and work on phones.
- Only current guild members can access data. Private-channel mentions never affect results,
  categories, counts, excerpts, or ordering. Preserve SPEC.md's session and visibility rules.
- No website scraping, provider API enrichment, model service, or job worker is required for
  the page to work. Remove the idle enrichment worker from the normal launch path when
  wiring up the MVP; preserve existing data and immutable migrations.
- Document running the bot and website with the project-local Python, and publishing only
  the website through HTTPS. Verify the core flow with a controlled Discord guild.
- Run Ruff, mypy, and offline tests; keep live integration checks outside the default suite.

## Out of scope

AI summaries, embeddings, model classifiers, MCP, provider-specific metadata integrations,
project lifecycle tracking, refresh scheduling, Markdown reports, GitHub runners/agents,
and extra queue or search services are not planned features. Reconsider only if a real
need appears after friends use the website.

The original numbered implementation plan is historical background. This file and the
current scope in SPEC.md take precedence over its superseded feature briefs. Existing
unused schema/code can remain until a small removal is needed; do not rewrite the working
collector or migrate data just to make the repository look smaller.
