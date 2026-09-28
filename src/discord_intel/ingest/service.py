"""Discord-independent parsing and transactional message persistence."""

from dataclasses import dataclass

from discord_intel.config import Settings
from discord_intel.db import Database, Repository, transaction, utc_timestamp
from discord_intel.urls import CanonicalURL, URLOccurrence, canonicalize_url, extract_urls


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    guild_id: str
    guild_name: str
    channel_id: str
    channel_name: str
    channel_kind: str
    author_id: str
    author_display_name: str
    author_username: str
    author_is_bot: bool
    message_id: str
    content: str
    created_at: str
    edited_at: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionResult:
    message_id: str
    accepted: bool
    occurrence_count: int
    enrichment_jobs_enqueued: int


class IngestionService:
    """Persist an allowlisted message and its URL occurrences without Discord types."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        repository: Repository | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.repository = repository or Repository()

    async def ingest_message(
        self,
        message: IncomingMessage,
        *,
        reconcile_occurrences: bool = False,
        update_backfill_checkpoint: bool = False,
    ) -> IngestionResult:
        if (
            message.guild_id != self.settings.discord_guild_id
            or message.channel_id not in self.settings.allowed_source_channel_ids
        ):
            return IngestionResult(
                message_id=message.message_id,
                accepted=False,
                occurrence_count=0,
                enrichment_jobs_enqueued=0,
            )

        parsed_urls: list[tuple[int, URLOccurrence, CanonicalURL]] = []
        for occurrence_index, occurrence in enumerate(extract_urls(message.content)):
            try:
                canonical = canonicalize_url(occurrence.raw_url)
            except ValueError:
                continue
            parsed_urls.append((occurrence_index, occurrence, canonical))

        ingested_at = utc_timestamp()
        async with self.database.connection() as connection:
            async with transaction(connection):
                await self.repository.upsert_guild(
                    connection, message.guild_id, message.guild_name, timestamp=ingested_at
                )
                await self.repository.upsert_channel(
                    connection,
                    message.channel_id,
                    message.guild_id,
                    message.channel_name,
                    message.channel_kind,
                    timestamp=ingested_at,
                )
                await self.repository.upsert_author(
                    connection,
                    message.author_id,
                    message.author_display_name,
                    message.author_username,
                    is_bot=message.author_is_bot,
                    timestamp=ingested_at,
                )
                if reconcile_occurrences:
                    await connection.execute(
                        "DELETE FROM message_links WHERE message_id = ?",
                        (message.message_id,),
                    )
                await self.repository.upsert_message(
                    connection,
                    message.message_id,
                    message.channel_id,
                    message.author_id,
                    message.content,
                    message.created_at,
                    edited_at=message.edited_at,
                    has_links=bool(parsed_urls),
                    ingested_at=ingested_at,
                )

                for occurrence_index, occurrence, canonical in parsed_urls:
                    link_id = await self.repository.upsert_link(
                        connection,
                        canonical.canonical_url,
                        occurrence.raw_url,
                        canonical.host,
                        canonical.domain,
                        message.created_at,
                        message.created_at,
                        provider=canonical.provider,
                        resource_type=canonical.resource_type,
                    )
                    await self.repository.upsert_message_link(
                        connection,
                        message.message_id,
                        link_id,
                        occurrence_index,
                        occurrence.raw_url,
                        occurrence.start_offset,
                        occurrence.end_offset,
                        created_at=message.created_at,
                    )
                if update_backfill_checkpoint:
                    await self.repository.upsert_channel_checkpoint(
                        connection,
                        message.channel_id,
                        message.message_id,
                        ingested_at,
                        "running",
                    )

        return IngestionResult(
            message_id=message.message_id,
            accepted=True,
            occurrence_count=len(parsed_urls),
            enrichment_jobs_enqueued=0,
        )

    async def prepare_backfill(
        self,
        guild_id: str,
        guild_name: str,
        channel_id: str,
        channel_name: str,
        channel_kind: str,
    ) -> str | None:
        if (
            guild_id != self.settings.discord_guild_id
            or channel_id not in self.settings.allowed_source_channel_ids
        ):
            raise ValueError("Backfill channel is outside the configured source allowlist")

        now = utc_timestamp()
        async with self.database.connection() as connection:
            async with transaction(connection):
                await self.repository.upsert_guild(
                    connection, guild_id, guild_name, timestamp=now
                )
                await self.repository.upsert_channel(
                    connection,
                    channel_id,
                    guild_id,
                    channel_name,
                    channel_kind,
                    timestamp=now,
                )
                await self.repository.upsert_channel_checkpoint(
                    connection, channel_id, None, now, "running"
                )
                return await self.repository.get_channel_checkpoint(connection, channel_id)

    async def advance_backfill_checkpoint(
        self, guild_id: str, channel_id: str, message_id: str
    ) -> None:
        if (
            guild_id != self.settings.discord_guild_id
            or channel_id not in self.settings.allowed_source_channel_ids
        ):
            raise ValueError("Backfill channel is outside the configured source allowlist")
        async with self.database.connection() as connection:
            async with transaction(connection):
                await self.repository.upsert_channel_checkpoint(
                    connection,
                    channel_id,
                    message_id,
                    utc_timestamp(),
                    "running",
                )

    async def get_backfill_checkpoint(self, channel_id: str) -> str | None:
        async with self.database.connection() as connection:
            return await self.repository.get_channel_checkpoint(connection, channel_id)

    async def finish_backfill(self, channel_id: str, state: str) -> None:
        if channel_id not in self.settings.allowed_source_channel_ids:
            raise ValueError("Backfill channel is outside the configured source allowlist")
        if state not in {"complete", "failed"}:
            raise ValueError("Backfill state must be complete or failed")
        async with self.database.connection() as connection:
            async with transaction(connection):
                await self.repository.upsert_channel_checkpoint(
                    connection, channel_id, None, utc_timestamp(), state
                )

    async def soft_delete_message(
        self, guild_id: str, channel_id: str, message_id: str
    ) -> bool:
        if (
            guild_id != self.settings.discord_guild_id
            or channel_id not in self.settings.allowed_source_channel_ids
        ):
            return False
        async with self.database.connection() as connection:
            async with transaction(connection):
                cursor = await connection.execute(
                    """
                    UPDATE messages
                    SET deleted_at = COALESCE(deleted_at, ?)
                    WHERE message_id = ? AND channel_id = ?
                    """,
                    (utc_timestamp(), message_id, channel_id),
                )
                return cursor.rowcount == 1
