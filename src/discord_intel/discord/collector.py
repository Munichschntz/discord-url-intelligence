"""Allowlisted live message collection through discord.py."""

from datetime import UTC, datetime

import discord

from discord_intel.config import Settings
from discord_intel.ingest import IncomingMessage, IngestionService


def _utc_isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _incoming_message(
    message: discord.Message,
    *,
    content: str | None = None,
    edited_at: datetime | None = None,
) -> IncomingMessage:
    guild = message.guild
    if guild is None:
        raise ValueError("Only guild messages can be ingested")
    channel_id = str(message.channel.id)
    effective_edit_time = edited_at if edited_at is not None else message.edited_at
    return IncomingMessage(
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
        content=message.content if content is None else content,
        created_at=_utc_isoformat(message.created_at),
        edited_at=(
            _utc_isoformat(effective_edit_time) if effective_edit_time is not None else None
        ),
    )


class DiscordCollector(discord.Client):
    """Receive guild messages and pass only configured sources to local ingestion."""

    def __init__(
        self,
        settings: Settings,
        ingestion: IngestionService,
        backfill_channel_id: str | None = None,
    ) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.settings = settings
        self.ingestion = ingestion
        self._source_channel_ids = frozenset(settings.allowed_source_channel_ids)
        self._bot_user_id: int | None = None
        self._backfill_channel_id = backfill_channel_id
        self._backfill_started = False
        self._backfill_count: int | None = None
        self._backfill_error: Exception | None = None

    async def on_ready(self) -> None:
        if self.user is not None:
            self._bot_user_id = self.user.id
        if self._backfill_channel_id is not None and not self._backfill_started:
            self._backfill_started = True
            try:
                self._backfill_count = await self.backfill_channel(self._backfill_channel_id)
            except Exception as error:
                self._backfill_error = error
                raise
            finally:
                await self.close()

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

        await self.ingestion.ingest_message(_incoming_message(message))

    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        cached_message = payload.cached_message
        guild_id = payload.guild_id
        if guild_id is None and cached_message is not None and cached_message.guild is not None:
            guild_id = cached_message.guild.id
        channel_id = str(payload.channel_id)
        if (
            guild_id is None
            or self.settings.discord_guild_id is None
            or str(guild_id) != self.settings.discord_guild_id
            or channel_id not in self._source_channel_ids
        ):
            return

        content = payload.data.get("content")
        if cached_message is not None:
            if not isinstance(content, str):
                return
            edited_at = discord.utils.parse_time(payload.data.get("edited_timestamp"))
            await self.ingestion.ingest_message(
                _incoming_message(cached_message, content=content, edited_at=edited_at),
                reconcile_occurrences=True,
            )
            return

        channel = self.get_channel(payload.channel_id)
        if channel is None:
            channel = await self.fetch_channel(payload.channel_id)
        fetch_message = getattr(channel, "fetch_message", None)
        if not callable(fetch_message):
            return
        current_message = await fetch_message(payload.message_id)
        await self.ingestion.ingest_message(
            _incoming_message(current_message),
            reconcile_occurrences=True,
        )

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        cached_message = payload.cached_message
        guild_id = payload.guild_id
        if guild_id is None and cached_message is not None and cached_message.guild is not None:
            guild_id = cached_message.guild.id
        if guild_id is None:
            return
        await self.ingestion.soft_delete_message(
            str(guild_id), str(payload.channel_id), str(payload.message_id)
        )

    async def backfill_channel(self, channel_id: str) -> int:
        if channel_id not in self._source_channel_ids:
            raise ValueError("Backfill channel is outside the configured source allowlist")
        if self.settings.discord_guild_id is None:
            raise ValueError("DISCORD_GUILD_ID is required for backfill")
        if self._bot_user_id is None:
            raise RuntimeError("The Discord client must be ready before backfill")

        channel = self.get_channel(int(channel_id))
        if channel is None:
            channel = await self.fetch_channel(int(channel_id))
        guild = getattr(channel, "guild", None)
        history = getattr(channel, "history", None)
        if guild is None or str(guild.id) != self.settings.discord_guild_id:
            raise ValueError("Backfill channel does not belong to the configured guild")
        if not callable(history):
            raise ValueError("Backfill is only supported for message channels")

        checkpoint = await self.ingestion.prepare_backfill(
            str(guild.id),
            guild.name,
            channel_id,
            str(getattr(channel, "name", channel_id)),
            str(getattr(channel, "type", "unknown")),
        )
        after = discord.Object(id=int(checkpoint)) if checkpoint is not None else None
        processed = 0
        try:
            async for message in history(limit=None, after=after, oldest_first=True):
                if message.author.id == self._bot_user_id:
                    await self.ingestion.advance_backfill_checkpoint(
                        str(guild.id), channel_id, str(message.id)
                    )
                else:
                    await self.ingestion.ingest_message(
                        _incoming_message(message),
                        update_backfill_checkpoint=True,
                    )
                processed += 1
        except Exception:
            await self.ingestion.finish_backfill(channel_id, "failed")
            raise

        await self.ingestion.finish_backfill(channel_id, "complete")
        return processed

    async def run_bot(self) -> int | None:
        if self.settings.discord_bot_token is None:
            raise ValueError("DISCORD_BOT_TOKEN is required to run the collector")
        if self.settings.discord_guild_id is None:
            raise ValueError("DISCORD_GUILD_ID is required to run the collector")
        if not self._source_channel_ids:
            raise ValueError("ALLOWED_SOURCE_CHANNEL_IDS must include at least one channel")
        if (
            self._backfill_channel_id is not None
            and self._backfill_channel_id not in self._source_channel_ids
        ):
            raise ValueError("Backfill channel is outside the configured source allowlist")
        await self.start(self.settings.discord_bot_token.get_secret_value())
        if self._backfill_error is not None:
            raise self._backfill_error
        return self._backfill_count