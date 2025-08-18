# File: helpers/db.py
import os
import time
import asyncio
import contextlib
from typing import List, Optional

__all__ = [
    "init",
    "close",
    "register_meme_message",
    "get_recent_post_ids",
]

import aiosqlite

# Path to the SQLite database. Can be overridden via env var.
DB_PATH = os.getenv("MEME_CACHE_DB", "data/meme_cache.db")

# Module level connection reused by all helpers
_conn: Optional[aiosqlite.Connection] = None
_lock = asyncio.Lock()
_queue: Optional[asyncio.Queue] = None
_flusher_task: Optional[asyncio.Task] = None

_FLUSH_INTERVAL = 5  # seconds


async def init() -> None:
    """Initialize the shared aiosqlite connection and ensure tables exist."""
    global _conn, _queue, _flusher_task

    async with _lock:
        if _conn is not None:
            return

        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = await aiosqlite.connect(DB_PATH)
        _conn.row_factory = aiosqlite.Row

        await _conn.execute(
            """
              CREATE TABLE IF NOT EXISTS meme_messages (
                message_id   TEXT PRIMARY KEY,
                channel_id   INTEGER,
                guild_id     INTEGER,
                url          TEXT,
                title        TEXT,
                post_id      TEXT,
                timestamp    INTEGER
              )
            """
        )
        await _conn.commit()

        _queue = asyncio.Queue()
        _flusher_task = asyncio.create_task(_flusher())


async def close() -> None:
    """Flush pending records and close the shared aiosqlite connection."""
    global _conn, _flusher_task, _queue

    if _flusher_task is not None:
        _flusher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _flusher_task
        _flusher_task = None

    if _queue is not None:
        await _flush_once()
        _queue = None

    if _conn is not None:
        await _conn.close()
        _conn = None


def register_meme_message(
    message_id: str,
    channel_id: int,
    guild_id: int,
    url: str,
    title: str,
    post_id: Optional[str] = None,
) -> None:
    """Queue a meme message record for later insertion."""
    if _conn is None or _queue is None:
        raise RuntimeError("Database not initialized")

    _queue.put_nowait(
        (
            message_id,
            channel_id,
            guild_id,
            url,
            title,
            post_id,
            int(time.time()),
        )
    )


async def get_recent_post_ids(channel_id: int, limit: int = 20) -> List[str]:
    """Return recent post IDs for the given channel."""
    if _conn is None:
        raise RuntimeError("Database not initialized")

    async with _conn.execute(
        """
          SELECT post_id
          FROM meme_messages
          WHERE channel_id = ?
          ORDER BY timestamp DESC
          LIMIT ?
        """,
        (channel_id, limit),
    ) as cursor:
        rows = await cursor.fetchall()

    return [r["post_id"] for r in rows if r["post_id"]]


async def _flush_once() -> None:
    """Flush all queued records in a single transaction."""
    if _conn is None or _queue is None:
        return

    batch = []
    while True:
        try:
            batch.append(_queue.get_nowait())
        except asyncio.QueueEmpty:
            break

    if not batch:
        return

    await _conn.execute("BEGIN")
    await _conn.executemany(
        """
          INSERT OR REPLACE INTO meme_messages
            (message_id, channel_id, guild_id, url, title, post_id, timestamp)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        batch,
    )
    await _conn.commit()

    for _ in batch:
        _queue.task_done()


async def _flusher() -> None:
    """Background task that periodically flushes the queue."""
    while True:
        await asyncio.sleep(_FLUSH_INTERVAL)
        await _flush_once()

