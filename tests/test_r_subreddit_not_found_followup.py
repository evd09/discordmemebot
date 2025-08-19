import os
import sys
import asyncio
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import memer.cogs.meme as meme_mod
from memer.cogs.meme import Meme


def test_r_subreddit_not_found_followup(monkeypatch):
    meme_cog = Meme.__new__(Meme)

    async def fake_subreddit(name, fetch=True):
        raise meme_mod.NotFound(SimpleNamespace(status=404))

    meme_cog.reddit = SimpleNamespace(subreddit=fake_subreddit)

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
        channel=SimpleNamespace(id=3),
    )

    async def fake_defer():
        pass

    ctx.defer = fake_defer

    captured = {}

    async def fake_followup_send(message, *, ephemeral=False):
        captured['message'] = message
        captured['ephemeral'] = ephemeral

    ctx.interaction = SimpleNamespace(followup=SimpleNamespace(send=fake_followup_send))

    asyncio.run(Meme.r_(meme_cog, ctx, 'nosuchsub'))

    assert captured['message'] == '❌ Could not find subreddit `nosuchsub`.'
    assert captured['ephemeral'] is True
