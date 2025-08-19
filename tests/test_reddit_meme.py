import os
import sys
from types import SimpleNamespace
import random
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from memer.reddit_meme import fetch_meme


class DummyCache:
    def __init__(self):
        self.cached = None
        self.failed = False

    def get_from_ram(self, keyword, nsfw=False):
        return None

    async def get_from_disk(self, keyword, nsfw=False):
        return None

    def is_disabled(self, keyword, nsfw=False):
        return False

    def cache_to_ram(self, keyword, posts, nsfw=False):
        self.cached = posts

    async def save_to_disk(self, keyword, posts, nsfw=False):
        pass

    def record_failure(self, keyword, nsfw=False):
        self.failed = True


class FakePost:
    def __init__(self, title, subreddit="testsub"):
        self.title = title
        self.url = "http://example.com/img.jpg"
        self.id = "xyz"
        self.subreddit = SimpleNamespace(display_name=subreddit)


class FakeSubreddit:
    def __init__(self, name, posts):
        self.posts = posts
        self.display_name = name

    async def hot(self, limit):
        items = self.posts if isinstance(self.posts, list) else self.posts.get("hot", [])
        for p in items:
            yield p

    async def top(self, limit):
        items = self.posts if isinstance(self.posts, list) else self.posts.get("top", [])
        for p in items:
            yield p

    async def new(self, limit):
        items = self.posts if isinstance(self.posts, list) else self.posts.get("new", [])
        for p in items:
            yield p


class FakeReddit:
    def __init__(self, posts):
        """
        posts can be either a list (same posts for all subs) or a dict mapping
        subreddit names to their specific posts.
        """
        self.posts = posts

    async def subreddit(self, name):
        if isinstance(self.posts, dict):
            return FakeSubreddit(name, self.posts[name])
        return FakeSubreddit(name, self.posts)

def test_keyword_filter_accepts_only_matching_posts():
    random.seed(0)
    posts = [FakePost("The Cat returns"), FakePost("concatenate words")]
    reddit = FakeReddit(posts)
    cache = DummyCache()

    result = asyncio.run(
        fetch_meme(
            reddit,
            ["testsub"],
            cache,
            keyword="cat",
            listings=("hot",),
            limit=10,
            extract_fn=lambda p: {"title": p.title, "media_url": "url", "subreddit": "testsub"},
        )
    )

    assert cache.cached is not None
    assert len(cache.cached) == 1
    assert cache.cached[0]["title"] == "The Cat returns"
    assert result.errors == []


def test_keyword_filter_rejects_non_matching_posts():
    random.seed(0)
    posts = [FakePost("concatenate"), FakePost("dog days")]
    reddit = FakeReddit(posts)
    cache = DummyCache()

    result = asyncio.run(
        fetch_meme(
            reddit,
            ["testsub"],
            cache,
            keyword="cat",
            listings=("hot",),
            limit=10,
            extract_fn=lambda p: {"title": p.title, "media_url": "url", "subreddit": "testsub"},
        )
    )

    assert cache.cached is None
    assert cache.failed is True
    assert result.errors == ["no valid posts"]


def test_fetch_meme_supports_top_listing():
    random.seed(0)
    posts = [FakePost("Top meme")]
    reddit = FakeReddit(posts)
    cache = DummyCache()

    result = asyncio.run(
        fetch_meme(
            reddit,
            ["testsub"],
            cache,
            listings=("top",),
            limit=10,
            extract_fn=lambda p: {
                "title": p.title,
                "media_url": "url",
                "subreddit": "testsub",
            },
        )
    )

    assert result.listing == "top"


def test_keyword_search_across_multiple_subreddits():
    random.seed(0)
    post_map = {
        "sub1": [FakePost("cat in sub1", subreddit="sub1"), FakePost("doggo", subreddit="sub1")],
        "sub2": [FakePost("another cat here", subreddit="sub2"), FakePost("bird", subreddit="sub2")],
    }
    reddit = FakeReddit(post_map)
    cache = DummyCache()

    result = asyncio.run(
        fetch_meme(
            reddit,
            ["sub1", "sub2"],
            cache,
            keyword="cat",
            listings=("hot",),
            limit=10,
            extract_fn=lambda p: {"title": p.title, "media_url": "url", "subreddit": p.subreddit.display_name},
        )
    )

    assert cache.cached is not None
    titles = {p["title"] for p in cache.cached}
    assert titles == {"cat in sub1", "another cat here"}
    assert result.errors == []
    assert result.source_subreddit in {"sub1", "sub2"}


def test_keyword_tries_multiple_listings():
    random.seed(0)
    post_map = {
        "sub1": {
            "hot": [FakePost("dog", subreddit="sub1")],
            "new": [FakePost("cat appears", subreddit="sub1")],
        }
    }
    reddit = FakeReddit(post_map)
    cache = DummyCache()

    result = asyncio.run(
        fetch_meme(
            reddit,
            ["sub1"],
            cache,
            keyword="cat",
            listings=("hot", "new"),
            limit=10,
            extract_fn=lambda p: {"title": p.title, "media_url": "url", "subreddit": p.subreddit.display_name},
        )
    )

    assert result.listing == "new"
    assert cache.cached is not None
