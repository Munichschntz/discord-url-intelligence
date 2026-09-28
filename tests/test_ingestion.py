from dataclasses import replace
from pathlib import Path

import pytest

from discord_intel.config import Settings
from discord_intel.db import Database
from discord_intel.ingest import IncomingMessage, IngestionService


def _message(message_id: str, content: str) -> IncomingMessage:
    return IncomingMessage(
        guild_id="100",
        guild_name="Example Guild",
        channel_id="200",
        channel_name="links",
        channel_kind="text",
        author_id="300",
        author_display_name="Ada",
        author_username="ada",
        author_is_bot=False,
        message_id=message_id,
        content=content,
        created_at="2026-09-27T00:00:00.000000Z",
    )


@pytest.mark.asyncio
async def test_shared_ingestion_archives_messages_and_deduplicates_link_jobs(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "ingestion.sqlite3")
    await database.initialize()
    settings = Settings(
        _env_file=None,
        discord_guild_id="100",
        allowed_source_channel_ids=["200"],
    )
    service = IngestionService(database, settings)
    repeated_url = "https://github.com/owner/repo"

    first_message = _message("400", f"Useful: {repeated_url} and again {repeated_url}")
    first_result = await service.ingest_message(first_message)
    replay_result = await service.ingest_message(first_message)
    second_result = await service.ingest_message(_message("401", repeated_url))
    no_link_result = await service.ingest_message(_message("402", "No link here"))

    assert first_result.occurrence_count == 2
    assert first_result.accepted
    assert first_result.enrichment_jobs_enqueued == 0
    assert replay_result.occurrence_count == 2
    assert replay_result.enrichment_jobs_enqueued == 0
    assert second_result.occurrence_count == 1
    assert second_result.enrichment_jobs_enqueued == 0
    assert no_link_result.occurrence_count == 0
    assert no_link_result.accepted

    rejected_result = await service.ingest_message(
        IncomingMessage(
            guild_id="100",
            guild_name="Example Guild",
            channel_id="201",
            channel_name="private",
            channel_kind="text",
            author_id="300",
            author_display_name="Ada",
            author_username="ada",
            author_is_bot=False,
            message_id="403",
            content="https://github.com/private/repo",
            created_at="2026-09-27T00:00:00.000000Z",
        )
    )
    assert not rejected_result.accepted

    async with database.connection() as connection:
        counts = await (
            await connection.execute(
                "SELECT (SELECT count(*) FROM links), "
                "(SELECT count(*) FROM messages), "
                "(SELECT count(*) FROM message_links), "
                "(SELECT count(*) FROM jobs)"
            )
        ).fetchone()
        assert tuple(counts) == (1, 3, 3, 0)
        archived = await (
            await connection.execute(
                "SELECT has_links FROM messages WHERE message_id = '402'"
            )
        ).fetchone()
        assert archived[0] == 0


@pytest.mark.asyncio
async def test_checkpoint_resume_edit_reconcile_and_soft_delete(tmp_path: Path) -> None:
    database = Database(tmp_path / "lifecycle.sqlite3")
    await database.initialize()
    settings = Settings(
        _env_file=None,
        discord_guild_id="100",
        allowed_source_channel_ids=["200"],
    )
    service = IngestionService(database, settings)
    original = _message(
        "400",
        "https://github.com/owner/alpha https://github.com/owner/alpha",
    )

    assert await service.prepare_backfill("100", "Example Guild", "200", "links", "text") is None
    await service.ingest_message(original, update_backfill_checkpoint=True)
    resumed_service = IngestionService(database, settings)
    assert await resumed_service.get_backfill_checkpoint("200") == "400"

    one_occurrence = replace(
        original,
        content="https://github.com/owner/alpha",
        edited_at="2026-09-27T00:05:00.000000Z",
    )
    await resumed_service.ingest_message(one_occurrence, reconcile_occurrences=True)
    async with database.connection() as connection:
        occurrence_count = await (
            await connection.execute(
                "SELECT count(*) FROM message_links WHERE message_id = '400'"
            )
        ).fetchone()
    assert occurrence_count[0] == 1

    edited = replace(
        one_occurrence,
        content="https://github.com/owner/beta",
        edited_at="2026-09-27T00:06:00.000000Z",
    )
    await resumed_service.ingest_message(edited, reconcile_occurrences=True)
    assert await resumed_service.soft_delete_message("100", "200", "400")
    await resumed_service.finish_backfill("200", "complete")

    async with database.connection() as connection:
        counts = await (
            await connection.execute(
                "SELECT (SELECT count(*) FROM links), "
                "(SELECT count(*) FROM message_links), "
                "(SELECT count(*) FROM messages WHERE deleted_at IS NOT NULL)"
            )
        ).fetchone()
        assert tuple(counts) == (2, 1, 1)
        association = await (
            await connection.execute(
                """
                SELECT links.canonical_url
                FROM message_links
                JOIN links USING (link_id)
                WHERE message_links.message_id = '400'
                """
            )
        ).fetchone()
        assert association[0] == "https://github.com/owner/beta"
        checkpoint = await (
            await connection.execute(
                "SELECT last_message_id, backfill_state "
                "FROM channel_checkpoints WHERE channel_id = '200'"
            )
        ).fetchone()
        assert tuple(checkpoint) == ("400", "complete")
