import os
import sys
import asyncio
from types import SimpleNamespace
from discord import Embed

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from memer.helpers.meme_utils import send_meme


class DummyCtx:
    def __init__(self):
        self.sent = None
        self.interaction = None

    async def send(self, content=None, embed=None):
        self.sent = (content, embed)
        return SimpleNamespace(id=123)


def test_send_meme_handles_query_params_for_images():
    ctx = DummyCtx()
    embed = Embed(title="test")
    url = "https://example.com/image.png?width=200&height=200"
    asyncio.run(send_meme(ctx, url=url, embed=embed))

    content, returned_embed = ctx.sent
    assert content is None
    assert returned_embed is embed
    assert embed.image.url == url
