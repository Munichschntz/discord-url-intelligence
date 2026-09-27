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

    async def ingest_message(self, message: IncomingMessage) -> IngestionResult:
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
        jobs_enqueued = 0
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
                    if await self.repository.enqueue_enrichment_job(
                        connection, link_id, ingested_at
                    ):
                        jobs_enqueued += 1

        return IngestionResult(
            message_id=message.message_id,
            accepted=True,
            occurrence_count=len(parsed_urls),
            enrichment_jobs_enqueued=jobs_enqueued,
        )