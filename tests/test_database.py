from pathlib import Path
from shutil import copyfile

import aiosqlite
import pytest

from discord_intel.db import Database, MigrationChecksumError, MigrationError


@pytest.mark.asyncio
async def test_initialize_creates_core_schema_and_enables_pragmas(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.sqlite3")

    await database.initialize()
    await database.initialize()

    async with database.connection() as connection:
        assert (await (await connection.execute("PRAGMA foreign_keys")).fetchone())[0] == 1
        assert (await (await connection.execute("PRAGMA journal_mode")).fetchone())[0] == "wal"
        assert (await (await connection.execute("PRAGMA synchronous")).fetchone())[0] == 1
        assert (await (await connection.execute("PRAGMA busy_timeout")).fetchone())[0] > 0
        tables = {
            row[0]
            for row in await (
                await connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            ).fetchall()
        }
        assert {"guilds", "channels", "authors", "messages", "links", "message_links"} <= tables
        assert {"search_fts", "web_search_fts", "schema_migrations"} <= tables
        applied = await (
            await connection.execute("SELECT count(*) FROM schema_migrations")
        ).fetchone()
        assert applied[0] == 2


@pytest.mark.asyncio
async def test_external_content_fts_triggers_track_insert_update_and_delete(tmp_path: Path) -> None:
    database = Database(tmp_path / "fts.sqlite3")
    await database.initialize()

    async with database.connection() as connection:
        await connection.execute("INSERT INTO guilds (guild_id, name) VALUES ('1', 'guild')")
        await connection.execute(
            "INSERT INTO channels (channel_id, guild_id, name, kind) "
            "VALUES ('2', '1', 'links', 'text')"
        )
        await connection.execute(
            "INSERT INTO authors (author_id, display_name, username) VALUES ('3', 'Ada', 'ada')"
        )
        await connection.execute(
            "INSERT INTO messages (message_id, channel_id, author_id, content, created_at) "
            "VALUES ('4', '2', '3', 'message', '2026-09-27T00:00:00Z')"
        )
        await connection.execute(
            "INSERT INTO links (canonical_url, first_original_url, host, "
            "domain, first_seen, last_seen) "
            "VALUES ('https://example.com/', 'https://example.com', 'example.com', 'example.com', "
            "'2026-09-27T00:00:00Z', '2026-09-27T00:00:00Z')"
        )
        await connection.execute(
            "INSERT INTO search_documents (link_id, title) VALUES (1, 'orchid')"
        )
        await connection.execute(
            "INSERT INTO web_search_documents (link_id, title) VALUES (1, 'orchid')"
        )
        await connection.commit()

        for fts_table in ("search_fts", "web_search_fts"):
            found = await (
                await connection.execute(
                    f"SELECT count(*) FROM {fts_table} WHERE {fts_table} MATCH 'orchid'"
                )
            ).fetchone()
            assert found[0] == 1

        await connection.execute("UPDATE search_documents SET title = 'fern' WHERE link_id = 1")
        await connection.execute("UPDATE web_search_documents SET title = 'fern' WHERE link_id = 1")
        await connection.commit()
        for fts_table in ("search_fts", "web_search_fts"):
            assert (
                await (
                    await connection.execute(
                        f"SELECT count(*) FROM {fts_table} WHERE {fts_table} MATCH 'orchid'"
                    )
                ).fetchone()
            )[0] == 0
            assert (
                await (
                    await connection.execute(
                        f"SELECT count(*) FROM {fts_table} WHERE {fts_table} MATCH 'fern'"
                    )
                ).fetchone()
            )[0] == 1

        await connection.execute("DELETE FROM search_documents WHERE link_id = 1")
        await connection.execute("DELETE FROM web_search_documents WHERE link_id = 1")
        await connection.commit()
        for fts_table in ("search_fts", "web_search_fts"):
            assert (
                await (
                    await connection.execute(
                        f"SELECT count(*) FROM {fts_table} WHERE {fts_table} MATCH 'fern'"
                    )
                ).fetchone()
            )[0] == 0


@pytest.mark.asyncio
async def test_changed_applied_migration_is_rejected(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    migration = migration_dir / "001_test.sql"
    migration.write_text("CREATE TABLE example (id INTEGER PRIMARY KEY);\n", encoding="utf-8")
    database = Database(tmp_path / "checksum.sqlite3", migrations_dir=migration_dir)
    await database.initialize()

    migration.write_text(
        "CREATE TABLE example (id INTEGER PRIMARY KEY, value TEXT);\n", encoding="utf-8"
    )
    with pytest.raises(MigrationChecksumError, match="has changed"):
        await database.initialize()


@pytest.mark.asyncio
async def test_new_migration_cannot_be_inserted_before_applied_versions(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "002_second.sql").write_text(
        "CREATE TABLE second (id INTEGER PRIMARY KEY);\n", encoding="utf-8"
    )
    database = Database(tmp_path / "ordering.sqlite3", migrations_dir=migration_dir)
    await database.initialize()

    (migration_dir / "001_first.sql").write_text(
        "CREATE TABLE first (id INTEGER PRIMARY KEY);\n", encoding="utf-8"
    )
    with pytest.raises(MigrationError, match="greater than all applied"):
        await database.initialize()


@pytest.mark.asyncio
async def test_failed_migration_rolls_back_schema_and_ledger(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    migration_dir.mkdir()
    (migration_dir / "001_broken.sql").write_text(
        "CREATE TABLE should_rollback (id INTEGER PRIMARY KEY);\nTHIS IS NOT SQL;\n",
        encoding="utf-8",
    )
    database = Database(tmp_path / "rollback.sqlite3", migrations_dir=migration_dir)

    with pytest.raises(aiosqlite.Error):
        await database.initialize()

    async with database.connection() as connection:
        objects = await (
            await connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'should_rollback'"
            )
        ).fetchall()
        assert objects == []
        assert (
            await (await connection.execute("SELECT count(*) FROM schema_migrations")).fetchone()
        )[0] == 0


@pytest.mark.asyncio
async def test_foreign_keys_reject_invalid_references(tmp_path: Path) -> None:
    database = Database(tmp_path / "foreign-key.sqlite3")
    await database.initialize()

    async with database.connection() as connection:
        with pytest.raises(aiosqlite.IntegrityError):
            await connection.execute(
                "INSERT INTO channels (channel_id, guild_id, name, kind) "
                "VALUES ('2', 'missing', 'x', 'text')"
            )


def test_sql_splitter_keeps_trigger_body_together() -> None:
    from discord_intel.db.database import _split_sql

    statements = list(
        _split_sql(
            "CREATE TABLE sample (id INTEGER);\n"
            "CREATE TRIGGER sample_ai AFTER INSERT ON sample BEGIN\n"
            "INSERT INTO sample VALUES (new.id + 1);\n"
            "END;\n"
        )
    )
    assert len(statements) == 2


@pytest.mark.asyncio
async def test_web_migration_preserves_existing_archive(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    source = Path(__file__).parents[1] / "migrations"
    initial = next(source.glob("001_*.sql"))
    copyfile(initial, migrations / initial.name)
    database = Database(tmp_path / "upgrade.sqlite3", migrations_dir=migrations)
    await database.initialize()
    async with database.connection() as connection:
        await connection.execute("INSERT INTO guilds (guild_id, name) VALUES ('1', 'preserved')")
        await connection.commit()
        old_ledger = await (await connection.execute("SELECT * FROM schema_migrations")).fetchall()
    copyfile(source / "002_web_auth.sql", migrations / "002_web_auth.sql")
    await database.initialize()
    async with database.connection() as connection:
        assert (await (await connection.execute("SELECT name FROM guilds")).fetchone())[0] == (
            "preserved"
        )
        ledger = await (await connection.execute("SELECT * FROM schema_migrations")).fetchall()
        assert tuple(ledger[0]) == tuple(old_ledger[0])
        assert len(ledger) == 2
        assert await (await connection.execute("SELECT * FROM web_sessions")).fetchall() == []
