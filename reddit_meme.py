import random
import asyncio
import logging
import os
import re
import yaml
from pathlib import Path
from typing import Optional, Callable, Sequence, List, MutableSet, Union, Dict
from dataclasses import dataclass
from cachetools import TTLCache
from asyncio import Semaphore
from collections import deque
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from asyncpraw import Reddit
from asyncpraw.models import Subreddit, Submission
from helpers.meme_utils import IMAGE_EXT

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)  # or INFO in prod

# --- Simple Rate Limiter (1 request per second) ---
_last_request = 0.0
_rate_lock = asyncio.Lock()
async def _throttle():
    global _last_request
    async with _rate_lock:
        now = asyncio.get_event_loop().time()
        elapsed = now - _last_request
        wait = max(0, 1.0 - elapsed)
        if wait:
            log.debug("Throttling: sleeping %.3fs before next Reddit request", wait)
            await asyncio.sleep(wait)
        _last_request = asyncio.get_event_loop().time()

# --- Dynamic, Hot-Reloadable Config ---
CONFIG_PATH = Path(os.getenv("REDDIT_MEME_CONFIG", "reddit_meme.config.yml"))
_CONFIG: Dict = {}

def load_config():
    global _CONFIG
    try:
        with open(CONFIG_PATH, 'r') as f:
            _CONFIG = yaml.safe_load(f) or {}
        log.info("Loaded reddit_meme config from %s: %r", CONFIG_PATH, _CONFIG)
    except Exception as e:
        log.warning("Failed to load config %s: %s", CONFIG_PATH, e)
        _CONFIG = {}

class _ConfigHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if Path(event.src_path) == CONFIG_PATH:
            log.info("Config file changed, reloading...")
            load_config()

observer = Observer()
observer.schedule(_ConfigHandler(), path=str(CONFIG_PATH.parent), recursive=False)
observer.daemon = True
observer.start()
load_config()

# --- Caches & Buffers ---
ID_CACHE = TTLCache(maxsize=_CONFIG.get('id_cache_maxsize', 10000), ttl=_CONFIG.get('id_cache_ttl', 6*3600))
HASH_CACHE = TTLCache(maxsize=_CONFIG.get('hash_cache_maxsize', 10000), ttl=_CONFIG.get('hash_cache_ttl', 6*3600))
WARM_CACHE: Dict[str, deque] = {}
_warmup_task: Optional[asyncio.Task] = None

# --- Exceptions ---
class RedditMemeError(Exception):
    "Base exception for reddit_meme failures."

class NoMemeFoundError(RedditMemeError):
    def __init__(self, tried: List[str], errors: List[str]):
        super().__init__(f"No meme found. Tried: {tried}. Errors: {errors}")
        self.tried = tried
        self.errors = errors

# --- Data Structures ---
@dataclass
class MemeResult:
    post: Optional[Submission]
    source_subreddit: Optional[str]
    listing: Optional[str]
    tried_subreddits: List[str]
    errors: List[str]
    picked_via: str  # e.g., 'hot', 'new', 'top', 'random', 'none'

# --- Internal Helpers ---
async def _fetch_listing_with_retry(
    subreddit: Subreddit,
    listing: str,
    limit: int,
    retries: int = 3,
    backoff: int = 1,
) -> List[Submission]:
    for attempt in range(1, retries+1):
        try:
            log.debug("Fetching %s from r/%s (limit=%d, attempt %d)", listing, subreddit.display_name, limit, attempt)
            await _throttle()
            posts: List[Submission] = []
            async for p in getattr(subreddit, listing)(limit=limit):
                posts.append(p)
            log.debug("Fetched %d posts from r/%s[%s]", len(posts), subreddit.display_name, listing)
            return posts
        except Exception as e:
            log.warning("Error fetching %s from %s (attempt %d/%d): %s", listing, subreddit.display_name, attempt, retries, e)
            await asyncio.sleep(backoff * (2 ** (attempt-1)))
    raise RedditMemeError(f"Failed to fetch listing {listing} from {subreddit.display_name} after {retries} retries")

async def _fetch_concurrent(
    subreddits: Sequence[Subreddit],
    listing: str,
    limit: int,
    max_concurrent: int = 5,
) -> List[Submission]:
    log.debug("Starting concurrent fetch for listing=%s across %d subreddits", listing, len(subreddits))
    sem = Semaphore(_CONFIG.get('max_concurrent', max_concurrent))
    async def fetch_one(sub: Subreddit):
        async with sem:
            return await _fetch_listing_with_retry(sub, listing, limit)
    tasks = [fetch_one(sub) for sub in subreddits]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    posts: List[Submission] = []
    for r in results:
        if isinstance(r, list):
            posts.extend(r)
    log.debug("Concurrent fetch for %s returned %d total posts", listing, len(posts))
    return posts

# --- Warmup Buffers ---
async def start_warmup(
    reddit: Reddit,
    subreddits: Sequence[Union[str, Subreddit]],
    listings: Sequence[str] = ("hot", "new"),
    limit: int = 75,
    interval: int = 600,
):
    global _warmup_task
    if _warmup_task and not _warmup_task.done():
        log.debug("Warmup already running, skipping start_warmup call")
        return
    log.info("Starting warmup task for %d subreddits every %ds", len(subreddits), interval)
    subs: List[Subreddit] = []
    for sub in subreddits:
        name = sub.display_name if isinstance(sub, Subreddit) else sub
        subs.append(reddit.subreddit(name))  # lazy Subreddit obj
    async def _loop():
        while True:
            for listing in listings:
                for sub in subs:
                    try:
                        posts = await _fetch_listing_with_retry(sub, listing, limit)
                        WARM_CACHE[f"{sub.display_name}_{listing}"] = deque(posts, maxlen=limit)
                        log.debug("Warmed buffer r/%s[%s] with %d items", sub.display_name, listing, len(posts))
                    except Exception as e:
                        log.warning("Warmup fetch error %s on %s: %s", listing, sub.display_name, e)
            await asyncio.sleep(_CONFIG.get('warmup_interval', interval))
    _warmup_task = asyncio.create_task(_loop())

async def stop_warmup():
    global _warmup_task
    if _warmup_task:
        log.info("Stopping warmup task")
        _warmup_task.cancel()
        _warmup_task = None

# --- Main Fetch Function ---
async def simple_random_meme(reddit: Reddit, subreddit_name: str) -> Optional[Submission]:
    """
    Try subreddit.random(); on failure fall back to picking one from hot().
    """
    try:
        sub: Subreddit = await reddit.subreddit(subreddit_name)
    except Exception as e:
        log.warning("Could not load r/%s: %s", subreddit_name, e)
        return None

    # 1️⃣ Try the true random endpoint
    try:
        p = await sub.random()  # this will 400 on most subs
        if p:
            log.debug("simple_random_meme: got %s via .random() on r/%s", p.id, subreddit_name)
            return p
    except Exception as e:
        log.debug("simple_random_meme: .random() failed for r/%s: %s", subreddit_name, e)

    # 2️⃣ Fallback → .hot()
    try:
        hot_posts = await _fetch_listing_with_retry(sub, "hot", limit=50)
        _exts = (".jpg", ".jpeg", ".png", ".gif", ".gifv", ".webm")
        candidates = [p for p in hot_posts if getattr(p, "url", "").lower().endswith(_exts)]
        if candidates:
            choice = random.choice(candidates)
            log.debug("simple_random_meme: got %s via .hot() on r/%s", choice.id, subreddit_name)
            return choice
    except Exception as e:
        log.warning("simple_random_meme: .hot() fallback failed for r/%s: %s", subreddit_name, e)

    return None

import re  # at the top of reddit_meme.py

async def fetch_meme(
    reddit: Reddit,
    subreddits: Sequence[Union[str, Subreddit]],
    cache_mgr,
    keyword: Optional[str] = None,
    listings: Sequence[str] = ("hot", "new"),
    limit: int = 75,
    extract_fn=None,
    filters: Optional[Sequence[Callable[[Submission], bool]]] = None
) -> MemeResult:
    from helpers.meme_utils import extract_post_data
    extract_fn = extract_fn or extract_post_data

    def is_valid_post(p: Submission) -> bool:
        if not p or not getattr(p, "url", None):
            return False
        if keyword:
            title = (p.title or "").lower()
            if not re.search(rf'\b{re.escape(keyword.lower())}\b', title):
                return False
        if filters and not all(f(p) for f in filters):
            return False
        return True

    # ─── keyword path ─────────────────────────────────────
    if keyword:
        # (1) RAM cache
        posts = cache_mgr.get_from_ram(keyword)
        if posts:
            valid = [p for p in posts if p.get("media_url")]
            if valid:
                chosen = random.choice(valid)
                return MemeResult(None, chosen.get("subreddit"), "cache_ram", [keyword], [], "cache")

        # (2) Disk cache
        posts = await cache_mgr.get_from_disk(keyword)
        if posts:
            chosen = random.choice([p for p in posts if p.get("media_url")])
            class Cached:
                title     = chosen["title"]
                permalink = f"/r/{chosen['subreddit']}/comments/{chosen['post_id']}/"
                url       = chosen["media_url"]
                id        = chosen["post_id"]
            return MemeResult(Cached, chosen["subreddit"], "cache_disk", [keyword], [], "cache")

        # (3) Disabled?
        if cache_mgr.is_disabled(keyword):
            return MemeResult(None, None, None, [keyword], ["disabled"], "fallback")

        # (4) Live Reddit fetch from a single randomly-chosen subreddit
        posts = []
        # pick exactly one sub per invocation
        sub_to_try = random.choice(subreddits)
        try:
            s_obj = await reddit.subreddit(sub_to_try)
            for listing in listings:
                async for post in getattr(s_obj, listing)(limit=limit):
                    if is_valid_post(post):
                        posts.append(extract_fn(post))
        except Exception:
            # if that one sub entirely fails, treat as “no posts”
            posts = []

        if posts:
            cache_mgr.cache_to_ram(keyword, posts)
            await cache_mgr.save_to_disk(keyword, posts)
            chosen = random.choice(posts)
            return MemeResult(None, chosen.get("subreddit"), "reddit", [keyword], [], "live")
        else:
            cache_mgr.record_failure(keyword)
            return MemeResult(None, None, None, [keyword], ["no valid posts"], "fallback")

        # ─── no-keyword fallback ──────────────────────────────
        tried: List[str] = []
        subs = list(subreddits)
        random.shuffle(subs)
        for name in subs:
            tried.append(name)
            try:
                sub_obj = await reddit.subreddit(name)
                for listing in listings:
                    async for post in getattr(sub_obj, listing)(limit=limit):
                        if is_valid_post(post):
                            data = extract_fn(post)
                            return MemeResult(None, name, listing, tried, [], "fallback")
            except Exception:
                continue

        # ─── ultimate random on the first subreddit ───────────
        raw = subreddits[0]
        chosen_sub = raw.display_name if hasattr(raw, "display_name") else str(raw)
        post = await simple_random_meme(reddit, chosen_sub)
        if post and is_valid_post(post):
            data = extract_fn(post)
            return MemeResult(None, chosen_sub, "random", tried, [], "random")

        # ─── total failure ────────────────────────────────────
        return MemeResult(None, None, None, tried, ["All fallback failed"], "none")