# File: helpers/db.py
import os, sqlite3, time
from typing import List

DB_PATH = os.getenv("MEME_CACHE_DB", "data/meme_cache.db")

def _ensure_tables():
    conn = sqlite3.connect(DB_PATH)
    with conn:
        conn.execute("""
          CREATE TABLE IF NOT EXISTS meme_messages (
            message_id   TEXT PRIMARY KEY,
            channel_id   INTEGER,
            guild_id     INTEGER,
            url          TEXT,
            title        TEXT,
            post_id      TEXT,
            timestamp    INTEGER
          )
        """)
    conn.close()

_ensure_tables()

def register_meme_message(
    message_id: str,
    channel_id: int,
    guild_id: int,
    url: str,
    title: str,
    post_id: str = None,
):
    conn = sqlite3.connect(DB_PATH)
    with conn:
        conn.execute("""
          INSERT OR REPLACE INTO meme_messages
            (message_id, channel_id, guild_id, url, title, post_id, timestamp)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
          message_id, channel_id, guild_id, url, title, post_id,
          int(time.time())
        ))
    conn.close()

def get_recent_post_ids(channel_id: int, limit: int = 20) -> List[str]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
      SELECT post_id
      FROM meme_messages
      WHERE channel_id = ?
      ORDER BY timestamp DESC
      LIMIT ?
    """, (channel_id, limit)).fetchall()
    conn.close()
    return [r["post_id"] for r in rows]
