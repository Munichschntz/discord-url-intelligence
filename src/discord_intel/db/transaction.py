"""Explicit transaction boundary for coherent persistence operations."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite


@asynccontextmanager
async def transaction(connection: aiosqlite.Connection) -> AsyncIterator[aiosqlite.Connection]:
    """Run a group of statements atomically, rolling back on errors or cancellation."""
    await connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
    except BaseException:
        await connection.rollback()
        raise
    else:
        await connection.commit()