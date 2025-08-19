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
    def __init__(self, title):
        self.title = title
        self.url = "http://example.com/img.jpg"
        self.id = "xyz"
        self.subreddit = SimpleNamespace(display_name="testsub")


class FakeSubreddit:
    def __init__(self, posts):
        self.posts = posts
        self.display_name = "testsub"

    async def hot(self, limit):
        for p in self.posts:
            yield p


class FakeReddit:
    def __init__(self, posts):
        self.posts = posts

    async def subreddit(self, name):
        return FakeSubreddit(self.posts)

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
