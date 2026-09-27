import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from discord_intel.db import Database
from discord_intel.db.repository import Repository
from discord_intel.db.transaction import transaction
from discord_intel.jobs.worker import BACKOFF, Worker, timestamp
from discord_intel.providers import Link, Metadata, PermanentFailure, Registry, TransientFailure

NOW = datetime(2026, 9, 27, tzinfo=UTC)


class FakeAdapter:
    def __init__(self, error=None):
        self.error = error

    def supports(self, link: Link) -> bool:
        return (
            link.canonical_url.startswith("https://example.com/") and link.resource_type == "page"
        )

    async def enrich(self, link: Link) -> Metadata:
        if self.error:
            raise self.error
        return Metadata("fake", "Title", "Description", {"ok": True}, "Body")


async def setup(tmp_path):
    database = Database(tmp_path / "worker.sqlite3")
    await database.initialize()
    repository = Repository()
    async with database.connection() as connection, transaction(connection):
        link_id = await repository.upsert_link(
            connection,
            "https://example.com/item",
            "https://example.com/item",
            "example.com",
            "example.com",
            timestamp(NOW),
            timestamp(NOW),
            resource_type="page",
        )
        assert await repository.enqueue_enrichment_job(connection, link_id, timestamp(NOW))
        assert not await repository.enqueue_enrichment_job(connection, link_id, timestamp(NOW))
    return database


async def rows(database, table):
    async with database.connection() as connection:
        return await (await connection.execute(f"SELECT * FROM {table}")).fetchall()


@pytest.mark.asyncio
async def test_success_atomic_claim_and_rebuild(tmp_path: Path):
    database = await setup(tmp_path)
    workers = [Worker(database, Registry(FakeAdapter()), clock=lambda: NOW) for _ in range(2)]
    claims = await asyncio.gather(*(worker.claim() for worker in workers))
    assert sum(claim is not None for claim in claims) == 1
    claim = next(claim for claim in claims if claim is not None)
    assert (await rows(database, "jobs"))[0]["attempt_count"] == 1
    assert (await rows(database, "links"))[0]["enrichment_state"] == "running"
    await workers[0].finish(claim, await claim.adapter.enrich(claim.link))
    await workers[0].finish(claim, Metadata("fake", "Should not overwrite"))
    jobs = await rows(database, "jobs")
    assert [(row["kind"], row["status"]) for row in jobs] == [
        ("enrich", "succeeded"),
        ("search_rebuild", "pending"),
    ]
    assert (await rows(database, "links"))[0]["title"] == "Title"
    assert (await rows(database, "link_metadata"))[0]["readable_text"] == "Body"
    assert not await workers[0].run_once()  # Search implementation is a later milestone.


@pytest.mark.asyncio
async def test_retries_due_time_and_threshold(tmp_path: Path):
    database = await setup(tmp_path)
    now = NOW
    worker = Worker(database, Registry(FakeAdapter(TransientFailure("secret"))), clock=lambda: now)
    for attempt, delay in enumerate(BACKOFF, 1):
        assert await worker.run_once()
        job = (await rows(database, "jobs"))[0]
        assert job["status"] == "pending"
        assert job["attempt_count"] == attempt
        assert job["last_error"] == "TransientFailure"
        assert job["available_at"] == timestamp(now + timedelta(seconds=delay))
        assert not await worker.run_once()
        now += timedelta(seconds=delay)
    assert await worker.run_once()
    job = (await rows(database, "jobs"))[0]
    assert job["status"] == "failed" and job["attempt_count"] == 6
    assert len(await rows(database, "links")) == 1
    assert not await worker.run_once()


@pytest.mark.asyncio
async def test_permanent_failure_keeps_existing_metadata(tmp_path: Path):
    database = await setup(tmp_path)
    async with database.connection() as connection, transaction(connection):
        await connection.execute("UPDATE links SET title = 'Original'")
    worker = Worker(database, Registry(FakeAdapter(PermanentFailure())), clock=lambda: NOW)
    assert await worker.run_once()
    assert (await rows(database, "jobs"))[0]["status"] == "failed"
    assert (await rows(database, "links"))[0]["title"] == "Original"


@pytest.mark.asyncio
async def test_recovery_fences_old_claim_and_keeps_fresh_claims(tmp_path: Path):
    database = await setup(tmp_path)
    now = NOW
    worker = Worker(database, Registry(FakeAdapter()), clock=lambda: now)
    old_claim = await worker.claim()
    assert old_claim is not None
    assert await worker.recover() == 0
    now += timedelta(minutes=16)
    assert await worker.recover() == 1
    assert await worker.recover() == 0
    new_claim = await worker.claim()
    assert new_claim is not None and new_claim.attempt == 2
    await worker.finish(old_claim, Metadata("fake", "Old"))
    assert (await rows(database, "jobs"))[0]["status"] == "running"
    await worker.finish(new_claim, Metadata("fake", "New"))
    assert (await rows(database, "links"))[0]["title"] == "New"


@pytest.mark.asyncio
async def test_unsupported_provider_stays_pending(tmp_path: Path):
    database = await setup(tmp_path)
    worker = Worker(database, Registry(), clock=lambda: NOW)
    assert not await worker.run_once()
    job = (await rows(database, "jobs"))[0]
    assert job["status"] == "pending" and job["attempt_count"] == 0


@pytest.mark.asyncio
async def test_cancellation_can_be_recovered(tmp_path: Path):
    database = await setup(tmp_path)
    worker = Worker(database, Registry(FakeAdapter(asyncio.CancelledError())), clock=lambda: NOW)
    with pytest.raises(asyncio.CancelledError):
        await worker.run_once()
    assert (await rows(database, "jobs"))[0]["status"] == "running"
    restarted = Worker(database, Registry(FakeAdapter()), clock=lambda: NOW + timedelta(minutes=16))
    assert await restarted.recover() == 1
    assert await restarted.run_once()


@pytest.mark.asyncio
async def test_success_rolls_back_if_rebuild_enqueue_fails(tmp_path: Path):
    database = await setup(tmp_path)
    worker = Worker(database, Registry(FakeAdapter()), clock=lambda: NOW)
    claim = await worker.claim()
    assert claim is not None
    async with database.connection() as connection, transaction(connection):
        await connection.execute("""CREATE TRIGGER reject_rebuild BEFORE INSERT ON jobs
            WHEN new.kind = 'search_rebuild' BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
    with pytest.raises(Exception, match="test failure"):
        await worker.finish(claim, Metadata("fake", "Title"))
    assert (await rows(database, "jobs"))[0]["status"] == "running"
    assert (await rows(database, "links"))[0]["title"] is None
    assert not await rows(database, "link_metadata")


@pytest.mark.asyncio
async def test_collector_run_stops_worker_on_exit(tmp_path: Path, monkeypatch):
    from discord_intel import cli
    from discord_intel.config import Settings

    started = asyncio.Event()
    stopped = asyncio.Event()
    closed = asyncio.Event()

    class FakeWorker:
        def __init__(self, *args):
            pass

        async def run(self):
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

    class FakeCollector:
        def __init__(self, *args, **kwargs):
            pass

        async def run_bot(self):
            await started.wait()

        async def close(self):
            closed.set()

    monkeypatch.setattr(cli, "Worker", FakeWorker)
    monkeypatch.setattr(cli, "DiscordCollector", FakeCollector)
    await cli._run_collector(Settings(_env_file=None, database_path=tmp_path / "cli.sqlite3"))
    assert stopped.is_set() and closed.is_set()


@pytest.mark.asyncio
async def test_rebuild_enqueue_is_deduplicated_across_refreshes(tmp_path: Path):
    database = await setup(tmp_path)
    worker = Worker(database, Registry(FakeAdapter()), clock=lambda: NOW)
    assert await worker.run_once()
    async with database.connection() as connection, transaction(connection):
        await connection.execute(
            "INSERT INTO jobs (link_id, kind, available_at, dedupe_key) "
            "VALUES (1, 'enrich', ?, 'link:1:enrich')",
            (timestamp(NOW),),
        )
    assert await worker.run_once()
    jobs = await rows(database, "jobs")
    assert sum(row["kind"] == "search_rebuild" for row in jobs) == 1
    assert len(await rows(database, "link_metadata")) == 1
