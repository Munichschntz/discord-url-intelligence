"""Hashed, expiring SQLite sessions and single-use browser-bound login state."""

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime

import aiosqlite

from discord_intel.db import Database, transaction


def stamp(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


class AuthStore:
    def __init__(
        self,
        database: Database,
        secret: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.database, self.secret, self.clock = database, secret.encode(), clock

    def digest(self, token: str) -> str:
        return hmac.new(self.secret, token.encode(), hashlib.sha256).hexdigest()

    def csrf(self, token: str) -> str:
        return self.digest("logout:" + token)

    async def begin(self) -> tuple[str, str]:
        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        async with self.database.connection() as connection, transaction(connection):
            await connection.execute(
                "DELETE FROM web_login_states WHERE expires_at <= ?", (stamp(self.clock()),)
            )
            await connection.execute(
                "DELETE FROM web_sessions WHERE expires_at <= ?", (stamp(self.clock()),)
            )
            await connection.execute(
                "INSERT INTO web_login_states VALUES (?, ?, ?)",
                (self.digest(state), self.digest(browser), stamp(self.clock() + 300)),
            )
        return state, browser

    async def consume(self, state: str, browser: str) -> bool:
        if not state or not browser or len(state) > 128 or len(browser) > 128:
            return False
        async with self.database.connection() as connection, transaction(connection):
            cursor = await connection.execute(
                """DELETE FROM web_login_states WHERE state_hash = ? AND browser_hash = ?
                   AND expires_at > ? RETURNING state_hash""",
                (self.digest(state), self.digest(browser), stamp(self.clock())),
            )
            return await cursor.fetchone() is not None

    async def create(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = self.clock()
        async with self.database.connection() as connection, transaction(connection):
            await connection.execute(
                "INSERT INTO web_sessions VALUES (?, ?, ?, ?, ?)",
                (self.digest(token), user_id, stamp(now), stamp(now + 8 * 3600), stamp(now)),
            )
        return token

    async def read(self, token: str) -> aiosqlite.Row | None:
        if not token or len(token) > 128:
            return None
        async with self.database.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM web_sessions WHERE session_hash = ? AND expires_at > ?",
                (self.digest(token), stamp(self.clock())),
            )
            return await cursor.fetchone()

    async def verified(self, token: str) -> None:
        async with self.database.connection() as connection, transaction(connection):
            await connection.execute(
                "UPDATE web_sessions SET verified_at = ? WHERE session_hash = ?",
                (stamp(self.clock()), self.digest(token)),
            )

    async def delete(self, token: str) -> None:
        async with self.database.connection() as connection, transaction(connection):
            await connection.execute(
                "DELETE FROM web_sessions WHERE session_hash = ?", (self.digest(token),)
            )
