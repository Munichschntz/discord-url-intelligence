from pathlib import Path

import pytest

from discord_intel.db import Database, Repository, transaction


@pytest.mark.asyncio
async def test_canonical_link_is_shared_but_each_occurrence_is_stored(tmp_path: Path) -> None:
    database = Database(tmp_path / "repository.sqlite3")
    await database.initialize()
    repository = Repository()

    async with database.connection() as connection:
        async with transaction(connection):
            await repository.upsert_guild(
                connection, "1", "Guild", timestamp="2026-01-01T00:00:00Z"
            )
            await repository.upsert_channel(connection, "2", "1", "Links", "text")
            await repository.upsert_author(connection, "3", "Ada", "ada")
            await repository.upsert_message(
                connection,
                "10",
                "2",
                "3",
                "https://example.com https://example.com",
                "2026-01-02T00:00:00Z",
                has_links=True,
            )
            await repository.upsert_message(
                connection,
                "11",
                "2",
                "3",
                "https://example.com",
                "2026-01-03T00:00:00Z",
                has_links=True,
            )
            link_id = await repository.upsert_link(
                connection,
                "https://example.com/",
                "https://example.com",
                "example.com",
                "example.com",
                "2026-01-02T00:00:00Z",
                "2026-01-02T00:00:00Z",
            )
            repeated_link_id = await repository.upsert_link(
                connection,
                "https://example.com/",
                "https://example.com/",
                "example.com",
                "example.com",
                "2026-01-03T00:00:00Z",
                "2026-01-03T00:00:00Z",
            )
            assert repeated_link_id == link_id
            await repository.upsert_message_link(
                connection, "10", link_id, 0, "https://example.com", 0, 19
            )
            await repository.upsert_message_link(
                connection, "11", link_id, 0, "https://example.com", 0, 19
            )

        counts = await (
            await connection.execute(
                "SELECT (SELECT count(*) FROM links), (SELECT count(*) FROM messages), "
                "(SELECT count(*) FROM message_links)"
            )
        ).fetchone()
        assert tuple(counts) == (1, 2, 2)
        link = await (
            await connection.execute(
                "SELECT first_original_url, first_seen, last_seen FROM links WHERE link_id = ?",
                (link_id,),
            )
        ).fetchone()
        assert tuple(link) == (
            "https://example.com",
            "2026-01-02T00:00:00Z",
            "2026-01-03T00:00:00Z",
        )


@pytest.mark.asyncio
async def test_occurrence_upsert_is_idempotent_by_message_and_index(tmp_path: Path) -> None:
    database = Database(tmp_path / "occurrence.sqlite3")
    await database.initialize()
    repository = Repository()

    async with database.connection() as connection:
        async with transaction(connection):
            await repository.upsert_guild(connection, "1", "Guild")
            await repository.upsert_channel(connection, "2", "1", "Links", "text")
            await repository.upsert_author(connection, "3", "Ada", "ada")
            await repository.upsert_message(
                connection,
                "10",
                "2",
                "3",
                "https://example.com https://example.com",
                "2026-01-01T00:00:00Z",
            )
            link_id = await repository.upsert_link(
                connection,
                "https://example.com",
                "https://example.com",
                "example.com",
                "example.com",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            )
            occurrence_id = await repository.upsert_message_link(
                connection, "10", link_id, 0, "https://example.com", 0, 19
            )
            second_occurrence_id = await repository.upsert_message_link(
                connection, "10", link_id, 1, "https://example.com", 20, 39
            )
            repeated_id = await repository.upsert_message_link(
                connection, "10", link_id, 0, "https://example.com", 0, 19
            )

        count = await (
            await connection.execute("SELECT count(*) FROM message_links WHERE message_id = '10'")
        ).fetchone()
        assert occurrence_id == repeated_id
        assert second_occurrence_id != occurrence_id
        assert count[0] == 2

        await repository.upsert_message(
            connection,
            "10",
            "2",
            "3",
            "https://example.com https://example.com",
            "2026-01-01T00:00:00Z",
            deleted_at="2026-01-02T00:00:00Z",
        )
        await repository.upsert_message(
            connection,
            "10",
            "2",
            "3",
            "https://example.com https://example.com",
            "2026-01-01T00:00:00Z",
        )
        deleted_at = await (
            await connection.execute(
                "SELECT deleted_at FROM messages WHERE message_id = '10'"
            )
        ).fetchone()
        assert deleted_at[0] == "2026-01-02T00:00:00Z"
