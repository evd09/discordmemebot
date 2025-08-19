import os
import sys
import asyncio
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import memer.cogs.meme as meme_mod
from memer.cogs.meme import Meme

class DummyResponse:
    async def send_message(self, *args, **kwargs):
        pass

class DummyFollowup:
    async def send(self, *args, **kwargs):
        pass

class DummyInteraction:
    def __init__(self):
        self.response = DummyResponse()
        self.followup = DummyFollowup()

def test_nsfwmeme_in_sfw_channel_sets_no_reward():
    meme_cog = Meme.__new__(Meme)
    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(is_nsfw=lambda: False),
        interaction=DummyInteraction(),
    )
    asyncio.run(Meme.nsfwmeme(meme_cog, ctx))
    assert getattr(ctx, "_no_reward", False) is True

def test_meme_no_posts_sets_no_reward(monkeypatch):
    meme_cog = Meme.__new__(Meme)

    async def fake_fetch_meme_util(**kwargs):
        return SimpleNamespace(post=None, picked_via='cache')

    async def fake_simple_random_meme(reddit, sub):
        return None

    monkeypatch.setattr(meme_mod, 'fetch_meme_util', fake_fetch_meme_util)
    monkeypatch.setattr(meme_mod, 'get_guild_subreddits', lambda guild_id, kind: ['a'])
    monkeypatch.setattr(meme_mod, 'simple_random_meme', fake_simple_random_meme)

    meme_cog.reddit = SimpleNamespace()
    meme_cog.cache_service = SimpleNamespace(cache_mgr=None)

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3),
        interaction=DummyInteraction(),
    )
    async def dummy_defer():
        pass
    ctx.defer = dummy_defer

    asyncio.run(Meme.meme(meme_cog, ctx))
    assert getattr(ctx, "_no_reward", False) is True
