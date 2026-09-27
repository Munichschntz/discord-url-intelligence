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
    assert first_result.enrichment_jobs_enqueued == 1
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
        assert tuple(counts) == (1, 3, 3, 1)
        archived = await (
            await connection.execute(
                "SELECT has_links FROM messages WHERE message_id = '402'"
            )
        ).fetchone()
        assert archived[0] == 0