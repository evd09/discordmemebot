import asyncio
from discord.ext import tasks
from discord import app_commands
from discord.ext.commands import Context
from .reddit_cache import RedditCacheManager
from .meme_utils import extract_post_data
import yaml
import os

CONFIG_PATH = "config/cache.yml"
DEFAULTS = {
    "ram_cache_ttl": 900,
    "disk_cache_ttl": 3600,
    "keyword_disable_after": 1,
    "keyword_disable_ttl": 900,
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            try:
                return {**DEFAULTS, **yaml.safe_load(f)}
            except Exception as e:
                print(f"Failed to load {CONFIG_PATH}: {e}")
                return DEFAULTS
    return DEFAULTS

CONFIG = load_config()

class MemeCacheService:
    def __init__(self, reddit, config=None):
        config = config or {}

        self.max_ram_posts = config.get("max_ram_posts", 100)
        self.refresh_minutes = config.get("refresh_minutes", 15)
        self.disk_file = config.get("disk_file", "cache/meme_cache.db")

        self.reddit = reddit
        self.cache_mgr = RedditCacheManager(
            ram_ttl=config.get("ram_cache_ttl", 900),
            disk_ttl=config.get("disk_cache_ttl", 3600),
            keyword_failures=config.get("keyword_disable_after", 1),
            keyword_ttl=config.get("keyword_disable_ttl", 900),
        )
        self._fetch_semaphore = asyncio.Semaphore(2)
        self._fallback_subs = ["memes", "dankmemes", "funny"]
        self._started = False

    async def init(self):
        if self._started:
            return
        await self.cache_mgr.init()
        self.cache_refresh_loop.start()
        self.disk_flush_loop.start()
        self._started = True

    async def close(self):
        if not self._started:
            return
        self.cache_refresh_loop.cancel()
        self.disk_flush_loop.cancel()
        await self.cache_mgr.close()
        self._started = False

    async def get_cache_info(self) -> str:
        ram_keywords = list(self.cache_mgr.ram_cache.keys())
        ram_posts = sum(len(v["posts"]) for v in self.cache_mgr.ram_cache.values())
        async with self.cache_mgr.conn.execute("SELECT COUNT(*) FROM meme_cache") as cur:
            disk_count = (await cur.fetchone())[0]
        disabled = len(self.cache_mgr.disabled_keywords)

        return (
            f"🧠 RAM cache: {len(ram_keywords)} keywords, {ram_posts} posts\n"
            f"💾 Disk cache: {disk_count} total posts\n"
            f"⛔ Disabled keywords: {disabled}"
        )

    async def _fetch_keyword_posts(self, keyword):
        async def fetch_sub(sub_name):
            async with self._fetch_semaphore:
                try:
                    sub = await self.reddit.subreddit(sub_name)
                    sub_results = []
                    async for post in sub.hot(limit=25):
                        if keyword.lower() in (post.title or "").lower():
                            sub_results.append(extract_post_data(post))
                    return sub_results
                except Exception as e:
                    print(f"Error fetching {sub_name} for keyword {keyword}: {e}")
                    return []

        results = await asyncio.gather(*(fetch_sub(name) for name in self._fallback_subs))
        return [item for sublist in results for item in sublist]

    @tasks.loop(seconds=600)
    async def cache_refresh_loop(self):
        keywords = self.cache_mgr.get_all_cached_keywords()
        if not keywords:
            return
        await self.cache_mgr.refresh_keywords(keywords, self._fetch_keyword_posts)

    @tasks.loop(seconds=3600)
    async def disk_flush_loop(self):
        await self.cache_mgr.flush_expired_disk(ttl_seconds=CONFIG["disk_cache_ttl"])
        print("[Disk Flush] Expired disk entries cleaned up.")
