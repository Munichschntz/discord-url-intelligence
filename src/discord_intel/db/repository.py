"""Parameterized upserts for the normalized core schema."""

from datetime import UTC, datetime

import aiosqlite


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp with a stable precision and suffix."""
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _timestamp(value: str | None) -> str:
    return value if value is not None else utc_timestamp()


class Repository:
    """Core guild, channel, author, message, link, and occurrence upserts."""

    async def upsert_guild(
        self,
        connection: aiosqlite.Connection,
        guild_id: str,
        name: str,
        *,
        timestamp: str | None = None,
    ) -> None:
        now = _timestamp(timestamp)
        await connection.execute(
            """
            INSERT INTO guilds (guild_id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                name = excluded.name,
                updated_at = excluded.updated_at
            """,
            (guild_id, name, now, now),
        )

    async def upsert_channel(
        self,
        connection: aiosqlite.Connection,
        channel_id: str,
        guild_id: str,
        name: str,
        kind: str,
        *,
        web_visible: bool = False,
        timestamp: str | None = None,
    ) -> None:
        now = _timestamp(timestamp)
        await connection.execute(
            """
            INSERT INTO channels (
                channel_id, guild_id, name, kind, web_visible, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                guild_id = excluded.guild_id,
                name = excluded.name,
                kind = excluded.kind,
                web_visible = excluded.web_visible,
                updated_at = excluded.updated_at
            """,
            (channel_id, guild_id, name, kind, int(web_visible), now, now),
        )

    async def upsert_author(
        self,
        connection: aiosqlite.Connection,
        author_id: str,
        display_name: str,
        username: str,
        *,
        is_bot: bool = False,
        timestamp: str | None = None,
    ) -> None:
        now = _timestamp(timestamp)
        await connection.execute(
            """
            INSERT INTO authors (author_id, display_name, username, is_bot, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(author_id) DO UPDATE SET
                display_name = excluded.display_name,
                username = excluded.username,
                is_bot = excluded.is_bot,
                updated_at = excluded.updated_at
            """,
            (author_id, display_name, username, int(is_bot), now, now),
        )

    async def upsert_message(
        self,
        connection: aiosqlite.Connection,
        message_id: str,
        channel_id: str,
        author_id: str,
        content: str,
        created_at: str,
        *,
        edited_at: str | None = None,
        deleted_at: str | None = None,
        has_links: bool = False,
        ingested_at: str | None = None,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO messages (
                message_id, channel_id, author_id, content, created_at,
                edited_at, deleted_at, has_links, ingested_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                author_id = excluded.author_id,
                content = excluded.content,
                edited_at = excluded.edited_at,
                deleted_at = COALESCE(messages.deleted_at, excluded.deleted_at),
                has_links = excluded.has_links,
                ingested_at = excluded.ingested_at
            """,
            (
                message_id,
                channel_id,
                author_id,
                content,
                created_at,
                edited_at,
                deleted_at,
                int(has_links),
                _timestamp(ingested_at),
            ),
        )

    async def upsert_link(
        self,
        connection: aiosqlite.Connection,
        canonical_url: str,
        original_url: str,
        host: str,
        domain: str,
        first_seen: str,
        last_seen: str,
        *,
        provider: str | None = None,
        resource_type: str | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> int:
        await connection.execute(
            """
            INSERT INTO links (
                canonical_url, first_original_url, host, domain, provider,
                resource_type, title, description, first_seen, last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_url) DO UPDATE SET
                host = excluded.host,
                domain = excluded.domain,
                provider = COALESCE(excluded.provider, links.provider),
                resource_type = COALESCE(excluded.resource_type, links.resource_type),
                title = COALESCE(excluded.title, links.title),
                description = COALESCE(excluded.description, links.description),
                first_seen = MIN(links.first_seen, excluded.first_seen),
                last_seen = MAX(links.last_seen, excluded.last_seen)
            """,
            (
                canonical_url,
                original_url,
                host,
                domain,
                provider,
                resource_type,
                title,
                description,
                first_seen,
                last_seen,
            ),
        )
        cursor = await connection.execute(
            "SELECT link_id FROM links WHERE canonical_url = ?", (canonical_url,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("Link upsert did not produce a link row")
        return int(row["link_id"])

    async def upsert_message_link(
        self,
        connection: aiosqlite.Connection,
        message_id: str,
        link_id: int,
        occurrence_index: int,
        raw_url: str,
        start_offset: int,
        end_offset: int,
        *,
        created_at: str | None = None,
    ) -> int:
        await connection.execute(
            """
            INSERT INTO message_links (
                message_id, link_id, occurrence_index, raw_url,
                start_offset, end_offset, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id, occurrence_index) DO UPDATE SET
                link_id = excluded.link_id,
                raw_url = excluded.raw_url,
                start_offset = excluded.start_offset,
                end_offset = excluded.end_offset
            """,
            (
                message_id,
                link_id,
                occurrence_index,
                raw_url,
                start_offset,
                end_offset,
                _timestamp(created_at),
            ),
        )
        cursor = await connection.execute(
            """
            SELECT occurrence_id FROM message_links
            WHERE message_id = ? AND occurrence_index = ?
            """,
            (message_id, occurrence_index),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("Occurrence upsert did not produce a row")
        return int(row["occurrence_id"])

    async def enqueue_enrichment_job(
        self,
        connection: aiosqlite.Connection,
        link_id: int,
        available_at: str,
    ) -> bool:
        """Queue enrichment for a link that has not succeeded or previously failed."""
        cursor = await connection.execute(
            "SELECT enrichment_state FROM links WHERE link_id = ?", (link_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"Unknown link ID: {link_id}")
        if row["enrichment_state"] not in {"pending", "failed"}:
            return False

        cursor = await connection.execute(
            """
            INSERT INTO jobs (link_id, kind, status, available_at, dedupe_key)
            VALUES (?, 'enrich', 'pending', ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (link_id, available_at, f"link:{link_id}:enrich"),
        )
        return cursor.rowcount == 1
