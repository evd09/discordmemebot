# File: helpers/db.py
import os
import time
import asyncio
from typing import List, Optional

import aiosqlite

# Path to the SQLite database. Can be overridden via env var.
DB_PATH = os.getenv("MEME_CACHE_DB", "data/meme_cache.db")

# Module level connection reused by all helpers
_conn: Optional[aiosqlite.Connection] = None
_lock = asyncio.Lock()


async def init() -> None:
    """Initialize the shared aiosqlite connection and ensure tables exist."""
    global _conn

    async with _lock:
        if _conn is not None:
            return

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


async def close() -> None:
    """Close the shared aiosqlite connection."""
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


async def register_meme_message(
    message_id: str,
    channel_id: int,
    guild_id: int,
    url: str,
    title: str,
    post_id: str = None,
) -> None:
    """Insert or update a meme message record."""
    if _conn is None:
        raise RuntimeError("Database not initialized")

    await _conn.execute(
        """
          INSERT OR REPLACE INTO meme_messages
            (message_id, channel_id, guild_id, url, title, post_id, timestamp)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message_id,
            channel_id,
            guild_id,
            url,
            title,
            post_id,
            int(time.time()),
        ),
    )
    await _conn.commit()


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

    return [r["post_id"] for r in rows]

