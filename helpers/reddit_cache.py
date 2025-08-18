import os
import sqlite3
import asyncio
import time
from typing import Dict, List, Optional
from collections import defaultdict

import logging
log = logging.getLogger(__name__)

DB_PATH = os.getenv("MEME_CACHE_DB", "data/meme_cache.db")

class RedditCacheManager:
    def __init__(self, ram_ttl=900, disk_ttl=3600, keyword_failures=1, keyword_ttl=900):
        self.ram_ttl = ram_ttl
        self.disk_ttl = disk_ttl
        self.keyword_failures = keyword_failures
        self.keyword_ttl = keyword_ttl

        self.ram_cache: Dict[str, Dict] = {}  # { keyword: {"posts": [...], "timestamp": float} }
        self.disabled_keywords: Dict[str, float] = {}  # { keyword: timestamp_disabled }
        self.failed_count: Dict[str, int] = defaultdict(int)
        self.lock = asyncio.Lock()
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self._setup_db()

    def _setup_db(self):
        with self.conn:
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS meme_cache (
                    keyword TEXT NOT NULL,
                    subreddit TEXT NOT NULL,
                    post_id TEXT PRIMARY KEY,
                    title TEXT,
                    url TEXT,
                    media_url TEXT,
                    author TEXT,
                    is_nsfw BOOLEAN,
                    created_utc INTEGER,
                    cached_at INTEGER
                )
            ''')
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_keyword ON meme_cache(keyword)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_cached_at ON meme_cache(cached_at)")

    def is_disabled(self, keyword: str) -> bool:
        ts = self.disabled_keywords.get(keyword)
        if ts and (time.time() - ts < self.keyword_ttl):
            return True
        self.disabled_keywords.pop(keyword, None)
        return False

    def disable_keyword(self, keyword: str):
        self.disabled_keywords[keyword] = time.time()

    def cache_to_ram(self, keyword: str, posts: List[dict]):
        self.ram_cache[keyword] = {
            "posts": posts,
            "timestamp": time.time()
        }

    def get_from_ram(self, keyword: str) -> Optional[List[dict]]:
        entry = self.ram_cache.get(keyword)
        if entry:
            age = time.time() - entry["timestamp"]
            if age <= self.ram_ttl:
                log.debug(f"[cache:RAM] HIT for {keyword!r} (age={age:.0f}s)")
                return entry["posts"]
            else:
                log.debug(f"[cache:RAM] EXPIRED for {keyword!r} (age={age:.0f}s)")
                del self.ram_cache[keyword]
        else:
            log.debug(f"[cache:RAM] MISS for {keyword!r}")
        return None

    def get_from_disk(self, keyword: str) -> Optional[List[dict]]:
        rows = self.conn.execute(
            "SELECT * FROM meme_cache WHERE keyword = ?", (keyword,)
        ).fetchall()
        if rows:
            log.debug(f"[cache:DISK] HIT for {keyword!r} ({len(rows)} rows)")
            posts = [dict(row) for row in rows]
            # refill RAM after a disk‐hit
            self.cache_to_ram(keyword, posts)
            return posts
        else:
            log.debug(f"[cache:DISK] MISS for {keyword!r}")
        return None

    def save_to_disk(self, keyword: str, posts: List[dict]):
        now = int(time.time())

        rows = []
        for post in posts:
            rows.append((
                keyword,
                post.get("subreddit"),
                post.get("post_id"),
                post.get("title"),
                post.get("url"),
                post.get("media_url"),
                post.get("author"),
                int(post.get("is_nsfw", False)),
                int(post.get("created_utc", now)),
                now
            ))

        cur = self.conn.cursor()
        try:
            cur.executemany('''
                INSERT OR REPLACE INTO meme_cache
                (keyword, subreddit, post_id, title, url, media_url, author, is_nsfw, created_utc, cached_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', rows)
            self.conn.commit()
        except Exception as e:
            log.warning("Bulk insert failed: %s; retrying individually", e)
            self.conn.rollback()
            for row in rows:
                try:
                    cur.execute('''
                        INSERT OR REPLACE INTO meme_cache
                        (keyword, subreddit, post_id, title, url, media_url, author, is_nsfw, created_utc, cached_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', row)
                except Exception as ex:
                    log.error("Failed to cache post %s: %s", row[2], ex)
            self.conn.commit()

    def record_failure(self, keyword: str) -> bool:
        self.failed_count[keyword] += 1
        if self.failed_count[keyword] >= self.keyword_failures:
            self.disable_keyword(keyword)
            return True
        return False

    def clear_disabled(self):
        self.disabled_keywords.clear()
        self.failed_count.clear()

    def flush_expired_disk(self, ttl_seconds: Optional[int] = None):
        ttl = ttl_seconds or self.disk_ttl
        log.debug("[Cache] Flushing expired disk entries older than %ds", ttl)
        now = int(time.time())
        cutoff = now - ttl

        cur = self.conn.cursor()
        cur.execute("DELETE FROM meme_cache WHERE cached_at < ?", (cutoff,))
        self.conn.commit()  # ✅ commit delete transaction first

        # Now we can VACUUM
        try:
            self.conn.execute("VACUUM")
        except sqlite3.OperationalError as e:
            log.warning("VACUUM failed: %s", e)

    async def refresh_keywords(self, keyword_list: List[str], fetch_fn):
        async with self.lock:
            for keyword in keyword_list:
                try:
                    new_posts = await fetch_fn(keyword)
                    if new_posts:
                        self.cache_to_ram(keyword, new_posts)
                        self.save_to_disk(keyword, new_posts)
                except Exception as e:
                    print(f"[Refresh] Failed to refresh {keyword}: {e}")
            self.clear_disabled()

    def get_all_cached_keywords(self) -> List[str]:
        return list(self.ram_cache.keys())
