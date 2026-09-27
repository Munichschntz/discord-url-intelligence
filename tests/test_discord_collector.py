from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import discord
import pytest

from discord_intel.config import Settings
from discord_intel.db import Database, Repository, transaction
from discord_intel.discord import DiscordCollector
from discord_intel.ingest import IncomingMessage, IngestionService


class RecordingIngestionService:
    def __init__(self) -> None:
        self.messages: list[IncomingMessage] = []

    async def ingest_message(self, message: IncomingMessage) -> None:
        self.messages.append(message)


@pytest.mark.asyncio
async def test_collector_uses_minimum_intents_and_filters_events_without_connecting() -> None:
    settings = Settings(
        _env_file=None,
        discord_guild_id="100",
        allowed_source_channel_ids=["200"],
    )
    recorder = RecordingIngestionService()
    collector = DiscordCollector(settings, cast(IngestionService, recorder))
    collector._bot_user_id = 900

    assert collector.intents.guilds
    assert collector.intents.guild_messages
    assert collector.intents.message_content
    assert not collector.intents.members
    assert not collector.intents.presences

    def message(guild_id: int, channel_id: int, author_id: int) -> discord.Message:
        return cast(
            discord.Message,
            SimpleNamespace(
                guild=SimpleNamespace(id=guild_id, name="Guild"),
                channel=SimpleNamespace(id=channel_id, name="links", type="text"),
                author=SimpleNamespace(
                    id=author_id,
                    display_name="Ada",
                    name="ada",
                    bot=False,
                ),
                id=400,
                content="https://github.com/owner/repo",
                created_at=datetime(2026, 9, 27, tzinfo=UTC),
                edited_at=None,
            ),
        )

    await collector.on_message(message(100, 200, 300))
    await collector.on_message(message(101, 200, 300))
    await collector.on_message(message(100, 201, 300))
    await collector.on_message(message(100, 200, 900))

    assert len(recorder.messages) == 1
    accepted = recorder.messages[0]
    assert accepted.guild_id == "100"
    assert accepted.channel_id == "200"
    assert accepted.author_id == "300"
    assert accepted.message_id == "400"
    assert accepted.created_at == "2026-09-27T00:00:00.000000Z"


def _gateway_message(message_id: int, author_id: int, content: str) -> SimpleNamespace:
    return SimpleNamespace(
        guild=SimpleNamespace(id=100, name="Guild"),
        channel=SimpleNamespace(id=200, name="links", type="text"),
        author=SimpleNamespace(
            id=author_id,
            display_name="Ada",
            name="ada",
            bot=False,
        ),
        id=message_id,
        content=content,
        created_at=datetime(2026, 9, 27, tzinfo=UTC),
        edited_at=None,
    )


@pytest.mark.asyncio
async def test_backfill_resumes_after_checkpoint_and_advances_past_own_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(tmp_path / "backfill.sqlite3")
    await database.initialize()
    settings = Settings(
        _env_file=None,
        discord_guild_id="100",
        allowed_source_channel_ids=["200"],
    )
    service = IngestionService(database, settings)

    class HistoryChannel:
        guild = SimpleNamespace(id=100, name="Guild")
        id = 200
        name = "links"
        type = "text"

        def __init__(self) -> None:
            self.calls: list[tuple[int | None, discord.Object | None, bool | None]] = []
            self.messages = [
                _gateway_message(400, 300, "https://github.com/owner/repo"),
                _gateway_message(401, 900, "bot post"),
                _gateway_message(402, 301, "No URL"),
            ]

        def history(
            self,
            *,
            limit: int | None,
            after: discord.Object | None,
            oldest_first: bool,
        ):
            self.calls.append((limit, after, oldest_first))

            async def iterate():
                for message in self.messages:
                    if after is not None and message.id <= after.id:
                        continue
                    yield cast(discord.Message, message)

            return iterate()

    channel = HistoryChannel()
    collector = DiscordCollector(settings, cast(IngestionService, service))
    collector._bot_user_id = 900
    monkeypatch.setattr(collector, "get_channel", lambda _: cast(discord.abc.GuildChannel, channel))

    assert await collector.backfill_channel("200") == 3
    assert await collector.backfill_channel("200") == 0
    assert channel.calls[0] == (None, None, True)
    assert channel.calls[1][0] is None
    assert channel.calls[1][1].id == 402
    assert channel.calls[1][2] is True

    async with database.connection() as connection:
        counts = await (
            await connection.execute(
                "SELECT (SELECT count(*) FROM messages), "
                "(SELECT count(*) FROM links), "
                "(SELECT count(*) FROM message_links)"
            )
        ).fetchone()
        assert tuple(counts) == (2, 1, 1)


@pytest.mark.asyncio
async def test_raw_edit_and_delete_reconcile_current_occurrences(tmp_path: Path) -> None:
    database = Database(tmp_path / "raw-events.sqlite3")
    await database.initialize()
    settings = Settings(
        _env_file=None,
        discord_guild_id="100",
        allowed_source_channel_ids=["200"],
    )
    service = IngestionService(database, settings)
    original = IncomingMessage(
        guild_id="100",
        guild_name="Guild",
        channel_id="200",
        channel_name="links",
        channel_kind="text",
        author_id="300",
        author_display_name="Ada",
        author_username="ada",
        author_is_bot=False,
        message_id="400",
        content="https://github.com/owner/alpha",
        created_at="2026-09-27T00:00:00.000000Z",
    )
    await service.ingest_message(original)
    collector = DiscordCollector(settings, service)
    cached_message = cast(
        discord.Message,
        _gateway_message(400, 300, "https://github.com/owner/alpha"),
    )
    update = SimpleNamespace(
        guild_id=100,
        channel_id=200,
        message_id=400,
        cached_message=cached_message,
        data={
            "content": "https://github.com/owner/beta",
            "edited_timestamp": "2026-09-27T00:05:00+00:00",
        },
    )
    await collector.on_raw_message_edit(cast(discord.RawMessageUpdateEvent, update))
    deletion = SimpleNamespace(
        guild_id=100,
        channel_id=200,
        message_id=400,
        cached_message=None,
    )
    await collector.on_raw_message_delete(cast(discord.RawMessageDeleteEvent, deletion))

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
                FROM message_links JOIN links USING (link_id)
                WHERE message_links.message_id = '400'
                """
            )
        ).fetchone()
        assert association[0] == "https://github.com/owner/beta"


@pytest.mark.asyncio
async def test_backfill_preserves_channel_visibility(tmp_path: Path) -> None:
    database = Database(tmp_path / "visibility.sqlite3")
    await database.initialize()
    settings = Settings(
        _env_file=None,
        discord_guild_id="100",
        allowed_source_channel_ids=["200"],
    )
    service = IngestionService(database, settings)
    original = IncomingMessage(
        guild_id="100",
        guild_name="Guild",
        channel_id="200",
        channel_name="links",
        channel_kind="text",
        author_id="300",
        author_display_name="Ada",
        author_username="ada",
        author_is_bot=False,
        message_id="400",
        content="No URL",
        created_at="2026-09-27T00:00:00.000000Z",
    )
    await service.ingest_message(original)
    async with database.connection() as connection:
        async with transaction(connection):
            await Repository().upsert_channel(
                connection, "200", "100", "links", "text", web_visible=True
            )

    await service.prepare_backfill("100", "Guild", "200", "links", "text")
    await service.ingest_message(original, update_backfill_checkpoint=True)

    async with database.connection() as connection:
        visible = await (
            await connection.execute(
                "SELECT web_visible FROM channels WHERE channel_id = '200'"
            )
        ).fetchone()
    assert visible[0] == 1