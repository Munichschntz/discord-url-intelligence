"""Allowlisted live message collection through discord.py."""

from datetime import UTC, datetime

import discord

from discord_intel.config import Settings
from discord_intel.ingest import IncomingMessage, IngestionService


def _utc_isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class DiscordCollector(discord.Client):
    """Receive guild messages and pass only configured sources to local ingestion."""

    def __init__(self, settings: Settings, ingestion: IngestionService) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.settings = settings
        self.ingestion = ingestion
        self._source_channel_ids = frozenset(settings.allowed_source_channel_ids)
        self._bot_user_id: int | None = None

    async def on_ready(self) -> None:
        if self.user is not None:
            self._bot_user_id = self.user.id

    async def on_message(self, message: discord.Message) -> None:
        guild = message.guild
        if guild is None or self.settings.discord_guild_id is None:
            return
        if self._bot_user_id is not None and message.author.id == self._bot_user_id:
            return

        channel_id = str(message.channel.id)
        if (
            str(guild.id) != self.settings.discord_guild_id
            or channel_id not in self._source_channel_ids
        ):
            return

        await self.ingestion.ingest_message(
            IncomingMessage(
                guild_id=str(guild.id),
                guild_name=guild.name,
                channel_id=channel_id,
                channel_name=str(getattr(message.channel, "name", channel_id)),
                channel_kind=str(getattr(message.channel, "type", "unknown")),
                author_id=str(message.author.id),
                author_display_name=message.author.display_name,
                author_username=message.author.name,
                author_is_bot=message.author.bot,
                message_id=str(message.id),
                content=message.content,
                created_at=_utc_isoformat(message.created_at),
                edited_at=(
                    _utc_isoformat(message.edited_at) if message.edited_at is not None else None
                ),
            )
        )

    async def run_bot(self) -> None:
        if self.settings.discord_bot_token is None:
            raise ValueError("DISCORD_BOT_TOKEN is required to run the collector")
        if self.settings.discord_guild_id is None:
            raise ValueError("DISCORD_GUILD_ID is required to run the collector")
        if not self._source_channel_ids:
            raise ValueError("ALLOWED_SOURCE_CHANNEL_IDS must include at least one channel")
        await self.start(self.settings.discord_bot_token.get_secret_value())