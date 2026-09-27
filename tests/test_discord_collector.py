from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import discord
import pytest

from discord_intel.config import Settings
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