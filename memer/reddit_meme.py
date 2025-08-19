import random
import asyncio
import logging
from typing import Optional, Callable, Sequence, List, Union, Dict, AsyncIterator, Tuple
from dataclasses import dataclass
from cachetools import TTLCache
from asyncio import Semaphore
from collections import deque
from asyncpraw import Reddit
from asyncpraw.models import Subreddit, Submission
from memer.helpers.rate_limit import throttle
from memer.helpers.reddit_config import CONFIG

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)  # or INFO in prod

# --- Caches & Buffers ---
ID_CACHE = TTLCache(maxsize=CONFIG.get('id_cache_maxsize', 10000), ttl=CONFIG.get('id_cache_ttl', 6*3600))
HASH_CACHE = TTLCache(maxsize=CONFIG.get('hash_cache_maxsize', 10000), ttl=CONFIG.get('hash_cache_ttl', 6*3600))
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
    post_dict: Optional[dict] = None

# --- Internal Helpers ---
async def _fetch_listing_with_retry(
    subreddit: Subreddit,
    listing: str,
    limit: int,
    retries: int = 3,
    backoff: int = 1,
) -> AsyncIterator[Submission]:
    for attempt in range(1, retries + 1):
        try:
            log.debug(
                "Fetching %s from r/%s (limit=%d, attempt %d)",
                listing,
                subreddit.display_name,
                limit,
                attempt,
            )
            await throttle()
            count = 0
            async for p in getattr(subreddit, listing)(limit=limit):
                count += 1
                yield p
            log.debug(
                "Fetched %d posts from r/%s[%s]",
                count,
                subreddit.display_name,
                listing,
            )
            return
        except Exception as e:
            log.warning(
                "Error fetching %s from %s (attempt %d/%d): %s",
                listing,
                subreddit.display_name,
                attempt,
                retries,
                e,
            )
            await asyncio.sleep(backoff * (2 ** (attempt - 1)))
    raise RedditMemeError(
        f"Failed to fetch listing {listing} from {subreddit.display_name} after {retries} retries"
    )


async def _search_with_retry(
    subreddit: Subreddit,
    keyword: str,
    limit: int,
    retries: int = 3,
    backoff: int = 1,
    *,
    sort: str = "new",
    time_filter: str = "all",
    **search_kwargs,
) -> AsyncIterator[Submission]:
    """Search a subreddit for keyword with retry/backoff."""
    for attempt in range(1, retries + 1):
        try:
            log.debug(
                "Searching '%s' in r/%s (limit=%d, attempt %d)",
                keyword,
                subreddit.display_name,
                limit,
                attempt,
            )
            await throttle()
            count = 0
            try:
                async for p in subreddit.search(
                    keyword,
                    limit=limit,
                    sort=sort,
                    time_filter=time_filter,
                    params={"include_over_18": "on"},
                    **search_kwargs,
                ):
                    count += 1
                    yield p
            except TypeError:
                # Fallback for implementations that don't accept the extra
                # arguments used above.
                async for p in subreddit.search(keyword, limit=limit):
                    count += 1
                    yield p
            log.debug(
                "Search fetched %d posts from r/%s for '%s'",
                count,
                subreddit.display_name,
                keyword,
            )
            return
        except Exception as e:
            log.warning(
                "Error searching '%s' in r/%s (attempt %d/%d): %s",
                keyword,
                subreddit.display_name,
                attempt,
                retries,
                e,
            )
            await asyncio.sleep(backoff * (2 ** (attempt - 1)))
    raise RedditMemeError(
        f"Failed to search '{keyword}' in {subreddit.display_name} after {retries} retries",
    )


async def _fetch_concurrent(
    subreddits: Sequence[Subreddit],
    listing: str,
    limit: int,
    max_concurrent: int = 5,
) -> Dict[str, List[Submission]]:
    log.debug(
        "Starting concurrent fetch for listing=%s across %d subreddits",
        listing,
        len(subreddits),
    )
    sem = Semaphore(CONFIG.get("max_concurrent", max_concurrent))

    async def fetch_one(sub: Subreddit):
        async with sem:
            posts = [p async for p in _fetch_listing_with_retry(sub, listing, limit)]
            return sub.display_name, posts

    tasks = [fetch_one(sub) for sub in subreddits]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    posts_by_sub: Dict[str, List[Submission]] = {}
    for r in results:
        if isinstance(r, tuple):
            name, posts = r
            posts_by_sub[name] = posts
    log.debug(
        "Concurrent fetch for %s returned posts for %d subreddits",
        listing,
        len(posts_by_sub),
    )
    return posts_by_sub

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
    # Ensure we create actual Subreddit objects instead of un-awaited
    # coroutines. asyncpraw's ``reddit.subreddit`` returns a coroutine
    # (via ``SubredditHelper.__call__``) that must be awaited to produce
    # the ``Subreddit`` instance. The previous implementation stored the
    # coroutine objects directly in ``subs`` which triggered
    # ``RuntimeWarning: coroutine 'SubredditHelper.__call__' was never
    # awaited`` at runtime.  Gather all Subreddit objects up front so the
    # warmup loop works with real instances.
    names = [
        sub.display_name if isinstance(sub, Subreddit) else sub
        for sub in subreddits
    ]
    subs: List[Subreddit] = await asyncio.gather(
        *(reddit.subreddit(name) for name in names)
    )
    async def _loop():
        while True:
            tasks = [_fetch_concurrent(subs, listing, limit) for listing in listings]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for listing, res in zip(listings, results):
                if isinstance(res, dict):
                    for name, posts in res.items():
                        WARM_CACHE[f"{name}_{listing}"] = deque(posts, maxlen=limit)
                        log.debug("Warmed buffer r/%s[%s] with %d items", name, listing, len(posts))
                else:
                    log.warning("Warmup fetch error for %s: %s", listing, res)
            await asyncio.sleep(CONFIG.get("warmup_interval", interval))
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
        _exts = (".jpg", ".jpeg", ".png", ".gif", ".gifv", ".webm")
        count = 0
        choice = None
        async for p in _fetch_listing_with_retry(sub, "hot", limit=50):
            if getattr(p, "url", "").lower().endswith(_exts):
                count += 1
                if random.randrange(count) == 0:
                    choice = p
        if choice:
            log.debug(
                "simple_random_meme: got %s via .hot() on r/%s",
                choice.id,
                subreddit_name,
            )
            return choice
    except Exception as e:
        log.warning(
            "simple_random_meme: .hot() fallback failed for r/%s: %s",
            subreddit_name,
            e,
        )

    return None

async def fetch_meme(
    reddit: Reddit,
    subreddits: Sequence[Union[str, Subreddit]],
    cache_mgr,
    keyword: Optional[str] = None,
    listings: Sequence[str] = ("hot", "new", "top"),
    limit: int = 75,
    extract_fn=None,
    filters: Optional[Sequence[Callable[[Submission], bool]]] = None,
    nsfw: bool = False,
    exclude_ids: Optional[Sequence[str]] = None,
) -> MemeResult:
    from memer.helpers.meme_utils import extract_post_data
    extract_fn = extract_fn or extract_post_data

    regex = keyword is not None
    exclude_ids_set = set(exclude_ids or [])
    subreddit_names = {
        getattr(s, "display_name", str(s)).lower()
        for s in subreddits
    }

    RAND_SENTINEL = "__random__"
    ram_random: List[dict] = []
    disk_random: List[dict] = []
    ram_random_ids: set = set()
    disk_random_ids: set = set()
    random_cache_ids: set = set()
    random_cache_urls: set = set()
    if not keyword:
        ram_random = cache_mgr.get_from_ram(RAND_SENTINEL, nsfw=nsfw) or []
        ram_random_ids = {p.get("post_id") for p in ram_random if p.get("post_id")}
        disk_random = await cache_mgr.get_from_disk(RAND_SENTINEL, nsfw=nsfw) or []
        disk_random_ids = {p.get("post_id") for p in disk_random if p.get("post_id")}
        combined_random = ram_random + [p for p in disk_random if p.get("post_id") not in ram_random_ids]
        random_cache_ids = ram_random_ids | disk_random_ids
        random_cache_urls = {p.get("media_url") for p in combined_random if p.get("media_url")}
    else:
        combined_random = []

    def is_valid_post(p: Submission) -> bool:
        if not p or not getattr(p, "url", None):
            return False
        pid = getattr(p, "id", None)
        if pid and pid in ID_CACHE:
            return False
        if exclude_ids_set and pid in exclude_ids_set:
            return False
        url = getattr(p, "url", None)
        if url and url in HASH_CACHE:
            return False
        if not keyword:
            if pid and pid in random_cache_ids:
                return False
            if url and url in random_cache_urls:
                return False
        if regex and keyword.lower() not in (p.title or "").lower():
            return False
        if filters and not all(f(p) for f in filters):
            return False
        return True

    # ─── keyword path ─────────────────────────────────────
    if keyword:
        # (1) RAM cache
        posts = cache_mgr.get_from_ram(keyword, nsfw=nsfw)
        if posts:
            valid = [
                p
                for p in posts
                if p.get("media_url")
                and p.get("post_id") not in exclude_ids_set
                and p.get("subreddit", "").lower() in subreddit_names
            ]
            if valid:
                chosen = random.choice(valid)
                class Cached:
                    title = chosen["title"]
                    permalink = f"/r/{chosen['subreddit']}/comments/{chosen['post_id']}/"
                    url = chosen["media_url"]
                    id = chosen["post_id"]
                    author = chosen.get("author") or "[deleted]"

                ID_CACHE[chosen["post_id"]] = True
                if chosen.get("media_url"):
                    HASH_CACHE[chosen["media_url"]] = True
                return MemeResult(
                    Cached,
                    chosen.get("subreddit"),
                    "cache_ram",
                    [keyword],
                    [],
                    "cache",
                    chosen,
                )

        # (2) Disk cache
        posts = await cache_mgr.get_from_disk(keyword, nsfw=nsfw)
        if posts:
            valid = [
                p
                for p in posts
                if p.get("media_url")
                and p.get("post_id") not in exclude_ids_set
                and p.get("subreddit", "").lower() in subreddit_names
            ]
            if valid:
                chosen = random.choice(valid)
                class Cached:
                    title = chosen["title"]
                    permalink = f"/r/{chosen['subreddit']}/comments/{chosen['post_id']}/"
                    url = chosen["media_url"]
                    id = chosen["post_id"]
                    author = chosen.get("author") or "[deleted]"

                ID_CACHE[chosen["post_id"]] = True
                if chosen.get("media_url"):
                    HASH_CACHE[chosen["media_url"]] = True
                return MemeResult(
                    Cached,
                    chosen["subreddit"],
                    "cache_disk",
                    [keyword],
                    [],
                    "cache",
                    chosen,
                )

        # (3) Disabled?
        if cache_mgr.is_disabled(keyword, nsfw=nsfw):
            return MemeResult(None, None, None, [keyword], ["disabled"], "fallback")

        # (4) Live Reddit fetch across all provided subreddits
        posts: List[Tuple[Submission, dict]] = []
        listing_used: Optional[str] = None
        try:
            # create subreddit objects (concurrently)
            sub_objs = await asyncio.gather(
                *(reddit.subreddit(s) for s in subreddits)
            )

            # search each subreddit for the keyword first
            for sub_obj in sub_objs:
                try:
                    async for post in _search_with_retry(sub_obj, keyword, limit):
                        if is_valid_post(post):
                            data = extract_fn(post)
                            posts.append((post, data))
                except Exception:
                    # if search isn't supported or fails, skip to listings
                    continue

            if not posts:
                # fallback to listings if search yielded nothing
                for listing_choice in listings:
                    posts = []
                    posts_by_sub = await _fetch_concurrent(sub_objs, listing_choice, limit)
                    for sub_name, post_list in posts_by_sub.items():
                        for post in post_list:
                            if is_valid_post(post):
                                data = extract_fn(post)
                                posts.append((post, data))
                    if posts:
                        listing_used = listing_choice
                        break
            else:
                listing_used = "search"
        except Exception:
            posts = []

        if posts:
            cache_posts = [d for _, d in posts]
            cache_mgr.cache_to_ram(keyword, cache_posts, nsfw=nsfw)
            await cache_mgr.save_to_disk(keyword, cache_posts, nsfw=nsfw)
            chosen_post, chosen_data = random.choice(posts)
            if getattr(chosen_post, "id", None):
                ID_CACHE[chosen_post.id] = True
            url = getattr(chosen_post, "url", None)
            if url:
                HASH_CACHE[url] = True
            return MemeResult(
                chosen_post,
                chosen_data.get("subreddit"),
                listing_used,
                [keyword],
                [],
                "live",
                chosen_data,
            )
        else:
            cache_mgr.record_failure(keyword, nsfw=nsfw)
            return MemeResult(
                None,
                None,
                None,
                [keyword],
                ["no valid posts"],
                "fallback",
            )

    # ─── no-keyword fallback ──────────────────────────────
    tried: List[str] = []
    subs = list(subreddits)
    random.shuffle(subs)

    # 0️⃣ Check cache for random posts
    if combined_random:
        valid = [
            p
            for p in combined_random
            if p.get("media_url")
            and p.get("post_id") not in exclude_ids_set
            and p.get("post_id") not in ID_CACHE
            and p.get("media_url") not in HASH_CACHE
        ]
        if valid:
            chosen = random.choice(valid)
            class Cached:
                title = chosen["title"]
                permalink = f"/r/{chosen['subreddit']}/comments/{chosen['post_id']}/"
                url = chosen["media_url"]
                id = chosen["post_id"]
                author = chosen.get("author") or "[deleted]"

            ID_CACHE[chosen["post_id"]] = True
            if chosen.get("media_url"):
                HASH_CACHE[chosen["media_url"]] = True
            source_listing = "cache_ram" if chosen["post_id"] in ram_random_ids else "cache_disk"
            return MemeResult(
                Cached,
                chosen.get("subreddit"),
                source_listing,
                [chosen.get("subreddit")] if chosen.get("subreddit") else [],
                [],
                "cache",
                chosen,
            )

    # 1️⃣ Check warm cache buffers first
    for listing_choice in listings:
        for name in subs:
            key = f"{name}_{listing_choice}"
            buf = WARM_CACHE.get(key)
            if buf:
                while buf:
                    post = buf.pop()
                    if post and is_valid_post(post):
                        data = extract_fn(post)
                        existing_rand = cache_mgr.get_from_ram(RAND_SENTINEL, nsfw=nsfw) or []
                        if data.get("post_id") not in {p.get("post_id") for p in existing_rand}:
                            existing_rand.append(data)
                        cache_mgr.cache_to_ram(RAND_SENTINEL, existing_rand, nsfw=nsfw)
                        await cache_mgr.save_to_disk(RAND_SENTINEL, [data], nsfw=nsfw)
                        if getattr(post, "id", None):
                            ID_CACHE[post.id] = True
                        url = getattr(post, "url", None)
                        if url:
                            HASH_CACHE[url] = True
                        return MemeResult(post, name, listing_choice, [name], [], "warm", data)

    # 2️⃣ Live fetch
    for name in subs:
        tried.append(name)
        try:
            sub_obj = await reddit.subreddit(name)
            listing_choice = random.choice(listings)
            count = 0
            choice_post = None
            async for post in _fetch_listing_with_retry(sub_obj, listing_choice, limit):
                if is_valid_post(post):
                    count += 1
                    if random.randrange(count) == 0:
                        choice_post = post
            if choice_post:
                data = extract_fn(choice_post)
                key = f"{name}_{listing_choice}"
                buf = WARM_CACHE.setdefault(key, deque(maxlen=limit))
                buf.appendleft(choice_post)
                existing_rand = cache_mgr.get_from_ram(RAND_SENTINEL, nsfw=nsfw) or []
                if data.get("post_id") not in {p.get("post_id") for p in existing_rand}:
                    existing_rand.append(data)
                cache_mgr.cache_to_ram(RAND_SENTINEL, existing_rand, nsfw=nsfw)
                await cache_mgr.save_to_disk(RAND_SENTINEL, [data], nsfw=nsfw)
                if getattr(choice_post, "id", None):
                    ID_CACHE[choice_post.id] = True
                url = getattr(choice_post, "url", None)
                if url:
                    HASH_CACHE[url] = True
                return MemeResult(choice_post, name, listing_choice, tried, [], "fallback", data)
        except Exception:
            continue

    # ─── ultimate random on the first subreddit ───────────
    raw = subreddits[0]
    chosen_sub = raw.display_name if hasattr(raw, "display_name") else str(raw)
    post = await simple_random_meme(reddit, chosen_sub)
    if post and is_valid_post(post):
        data = extract_fn(post)
        existing_rand = cache_mgr.get_from_ram(RAND_SENTINEL, nsfw=nsfw) or []
        if data.get("post_id") not in {p.get("post_id") for p in existing_rand}:
            existing_rand.append(data)
        cache_mgr.cache_to_ram(RAND_SENTINEL, existing_rand, nsfw=nsfw)
        await cache_mgr.save_to_disk(RAND_SENTINEL, [data], nsfw=nsfw)
        if getattr(post, "id", None):
            ID_CACHE[post.id] = True
        url = getattr(post, "url", None)
        if url:
            HASH_CACHE[url] = True
        return MemeResult(post, chosen_sub, "random", tried, [], "random", data)

    # ─── total failure ────────────────────────────────────
    return MemeResult(None, None, None, tried, ["All fallback failed"], "none")
