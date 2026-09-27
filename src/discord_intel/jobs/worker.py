"""Single worker with short database transactions and bounded provider execution."""

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from discord_intel.db import Database
from discord_intel.db.transaction import transaction
from discord_intel.providers import Adapter, Link, Metadata, PermanentFailure, Registry

BACKOFF = (30, 120, 600, 3600, 21600)


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Claim:
    job_id: int
    attempt: int
    link: Link
    adapter: Adapter


class Worker:
    def __init__(
        self,
        database: Database,
        registry: Registry,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.database = database
        self.registry = registry
        self.clock = clock

    async def recover(self) -> int:
        """Recover abandoned claims at startup, without resetting their attempts."""
        now = self.clock()
        async with self.database.connection() as connection, transaction(connection):
            cursor = await connection.execute(
                """UPDATE jobs SET status = 'pending', started_at = NULL,
                       available_at = ?, last_error = 'Interrupted worker'
                   WHERE status = 'running' AND julianday(started_at) < julianday(?)
                   RETURNING link_id, kind""",
                (timestamp(now), timestamp(now - timedelta(minutes=15))),
            )
            rows = list(await cursor.fetchall())
            for row in rows:
                if row["kind"] == "enrich":
                    await connection.execute(
                        "UPDATE links SET enrichment_state = 'pending' WHERE link_id = ?",
                        (row["link_id"],),
                    )
            return len(rows)

    async def claim(self) -> Claim | None:
        if not self.registry.adapters:
            return None
        async with self.database.connection() as connection, transaction(connection):
            cursor = await connection.execute(
                """SELECT j.job_id, j.attempt_count, l.link_id, l.canonical_url,
                          l.resource_type
                   FROM jobs j JOIN links l ON l.link_id = j.link_id
                   WHERE j.status = 'pending' AND j.kind = 'enrich'
                     AND julianday(j.available_at) <= julianday(?)
                   ORDER BY j.available_at, j.job_id""",
                (timestamp(self.clock()),),
            )
            async for row in cursor:
                link = Link(row["link_id"], row["canonical_url"], row["resource_type"])
                adapter = self.registry.select(link)
                if adapter is None:
                    continue
                await connection.execute(
                    """UPDATE jobs SET status = 'running', attempt_count = attempt_count + 1,
                           started_at = ?, finished_at = NULL WHERE job_id = ?""",
                    (timestamp(self.clock()), row["job_id"]),
                )
                await connection.execute(
                    "UPDATE links SET enrichment_state = 'running' WHERE link_id = ?",
                    (link.link_id,),
                )
                return Claim(row["job_id"], row["attempt_count"] + 1, link, adapter)
        return None

    async def finish(
        self, claim: Claim, metadata: Metadata | None, error: Exception | None = None
    ) -> None:
        now = self.clock()
        # Serialize before opening the transaction; invalid adapter data is a job failure.
        data = json.dumps(metadata.data, sort_keys=True) if metadata is not None else ""
        retry = error is not None and not isinstance(error, PermanentFailure)
        retry = retry and claim.attempt <= len(BACKOFF)
        status = "succeeded" if error is None else ("pending" if retry else "failed")
        available = now + timedelta(seconds=BACKOFF[claim.attempt - 1]) if retry else now
        async with self.database.connection() as connection, transaction(connection):
            cursor = await connection.execute(
                """UPDATE jobs SET status = ?, available_at = ?, finished_at = ?,
                       last_error = ? WHERE job_id = ? AND status = 'running'
                       AND attempt_count = ?""",
                (
                    status,
                    timestamp(available),
                    None if retry else timestamp(now),
                    # Do not persist exception text: it can contain credentials or private URLs.
                    None if error is None else type(error).__name__,
                    claim.job_id,
                    claim.attempt,
                ),
            )
            if cursor.rowcount != 1:
                return  # A recovered/reclaimed job cannot be completed by its old owner.
            await connection.execute(
                "UPDATE links SET enrichment_state = ? WHERE link_id = ?",
                (status, claim.link.link_id),
            )
            if metadata is None:
                return
            await connection.execute(
                """INSERT INTO link_metadata
                       (link_id, provider, data_json, readable_text, fetched_at,
                        checked_at, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(link_id) DO UPDATE SET provider = excluded.provider,
                       data_json = excluded.data_json, readable_text = excluded.readable_text,
                       fetched_at = excluded.fetched_at, checked_at = excluded.checked_at,
                       content_hash = excluded.content_hash""",
                (
                    claim.link.link_id,
                    metadata.provider,
                    data,
                    metadata.readable_text,
                    timestamp(now),
                    timestamp(now),
                    hashlib.sha256((data + "\n" + metadata.readable_text).encode()).hexdigest(),
                ),
            )
            await connection.execute(
                """UPDATE links SET title = ?, description = ?, metadata_fetched_at = ?,
                       metadata_checked_at = ? WHERE link_id = ?""",
                (
                    metadata.title,
                    metadata.description,
                    timestamp(now),
                    timestamp(now),
                    claim.link.link_id,
                ),
            )
            await connection.execute(
                """INSERT INTO jobs (link_id, kind, available_at, dedupe_key)
                   VALUES (?, 'search_rebuild', ?, ?) ON CONFLICT DO NOTHING""",
                (claim.link.link_id, timestamp(now), f"link:{claim.link.link_id}:search_rebuild"),
            )

    async def run_once(self) -> bool:
        claim = await self.claim()
        if claim is None:
            return False
        try:
            async with asyncio.timeout(300):
                metadata = await claim.adapter.enrich(claim.link)
            # Validate serialization as part of the adapter boundary.
            json.dumps(metadata.data, sort_keys=True)
        except Exception as error:
            await self.finish(claim, None, error)
        else:
            await self.finish(claim, metadata)
        return True

    async def run(self) -> None:
        await self.recover()
        while True:
            if not await self.run_once():
                await asyncio.sleep(1)
