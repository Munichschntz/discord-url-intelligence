"""Async SQLite connections and append-only SQL migrations."""

import hashlib
import re
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


class MigrationError(RuntimeError):
    """Raised when a migration set cannot be applied safely."""


class MigrationChecksumError(MigrationError):
    """Raised when an applied migration has changed or disappeared."""


_MIGRATION_FILENAME = re.compile(r"^(\d+)_([a-z0-9][a-z0-9_-]*)\.sql$")
_MIGRATION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    filename TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL CHECK (length(checksum) = 64),
    applied_at TEXT NOT NULL
)
"""


def _split_sql(script: str) -> Iterator[str]:
    pending = ""
    for character in script:
        pending += character
        if character == ";" and sqlite3.complete_statement(pending):
            if pending.strip():
                yield pending.strip()
            pending = ""

    if pending.strip():
        if not sqlite3.complete_statement(pending):
            raise MigrationError("Migration contains an incomplete SQL statement")
        yield pending.strip()


def _version_for(path: Path) -> int:
    match = _MIGRATION_FILENAME.fullmatch(path.name)
    if match is None:
        raise MigrationError(f"Invalid migration filename: {path.name}")
    version = int(match.group(1))
    if version <= 0:
        raise MigrationError(f"Migration version must be positive: {path.name}")
    return version


class Database:
    """Owns connection setup and ordered migration application."""

    def __init__(
        self,
        path: str | Path,
        migrations_dir: str | Path | None = None,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        self.path = str(path) if str(path) == ":memory:" else Path(path)
        if migrations_dir is not None:
            self.migrations_dir = Path(migrations_dir)
        else:
            source_migrations = Path(__file__).resolve().parents[3] / "migrations"
            packaged_migrations = Path(__file__).resolve().parents[1] / "migrations"
            self.migrations_dir = (
                source_migrations if source_migrations.is_dir() else packaged_migrations
            )
        self.busy_timeout_ms = busy_timeout_ms

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[aiosqlite.Connection]:
        if self.path != ":memory:" and isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(
            str(self.path), timeout=self.busy_timeout_ms / 1_000
        )
        connection.row_factory = aiosqlite.Row
        try:
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("PRAGMA journal_mode = WAL")
            await connection.execute("PRAGMA synchronous = NORMAL")
            await connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            yield connection
        finally:
            await connection.close()

    def _migration_files(self) -> list[tuple[int, Path, bytes, str]]:
        if not self.migrations_dir.is_dir():
            raise MigrationError(f"Migration directory does not exist: {self.migrations_dir}")

        migrations: list[tuple[int, Path, bytes, str]] = []
        versions: set[int] = set()
        for path in sorted(self.migrations_dir.glob("*.sql")):
            version = _version_for(path)
            if version in versions:
                raise MigrationError(f"Duplicate migration version: {version}")
            versions.add(version)
            contents = path.read_bytes()
            try:
                script = contents.decode("utf-8")
            except UnicodeDecodeError as error:
                raise MigrationError(f"Migration is not UTF-8: {path.name}") from error
            checksum = hashlib.sha256(contents).hexdigest()
            migrations.append((version, path, contents, checksum))
            if not script.strip():
                raise MigrationError(f"Migration is empty: {path.name}")
        return sorted(migrations, key=lambda item: item[0])

    async def initialize(self) -> None:
        """Create the migration ledger and apply all pending migrations."""
        migrations = self._migration_files()
        files_by_version = {version: (path, checksum) for version, path, _, checksum in migrations}

        async with self.connection() as connection:
            await connection.execute(_MIGRATION_TABLE)
            await connection.commit()

            cursor = await connection.execute(
                "SELECT version, filename, checksum FROM schema_migrations ORDER BY version"
            )
            applied = await cursor.fetchall()
            for row in applied:
                expected = files_by_version.get(row["version"])
                if expected is None or expected[0].name != row["filename"]:
                    raise MigrationChecksumError(
                        f"Applied migration {row['version']} is missing or was renamed"
                    )
                if expected[1] != row["checksum"]:
                    raise MigrationChecksumError(
                        f"Applied migration {row['version']} has changed: {row['filename']}"
                    )

            applied_versions = {row["version"] for row in applied}
            if applied_versions:
                newest_applied = max(applied_versions)
                if any(
                    version not in applied_versions and version <= newest_applied
                    for version, _, _, _ in migrations
                ):
                    raise MigrationError(
                        "New migrations must have a version greater than all applied migrations"
                    )

            for version, path, contents, checksum in migrations:
                if version in applied_versions:
                    continue
                script = contents.decode("utf-8")
                await connection.execute("BEGIN IMMEDIATE")
                try:
                    cursor = await connection.execute(
                        "SELECT filename, checksum FROM schema_migrations WHERE version = ?",
                        (version,),
                    )
                    concurrent_row = await cursor.fetchone()
                    if concurrent_row is not None:
                        if (
                            concurrent_row["filename"] != path.name
                            or concurrent_row["checksum"] != checksum
                        ):
                            raise MigrationChecksumError(
                                f"Applied migration {version} changed during initialization"
                            )
                        await connection.commit()
                        continue

                    for statement in _split_sql(script):
                        await connection.execute(statement)
                    await connection.execute(
                        """
                        INSERT INTO schema_migrations (version, filename, checksum, applied_at)
                        VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                        """,
                        (version, path.name, checksum),
                    )
                    await connection.commit()
                except aiosqlite.OperationalError as error:
                    await connection.rollback()
                    if "fts5" in str(error).lower():
                        raise MigrationError(
                            "SQLite was built without FTS5 support required by this schema"
                        ) from error
                    raise
                except BaseException:
                    await connection.rollback()
                    raise