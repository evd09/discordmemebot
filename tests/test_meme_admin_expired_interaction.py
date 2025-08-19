import os
import sys
import asyncio
from types import SimpleNamespace
import time
import discord

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# augment discord stub from conftest
discord.SelectOption = SimpleNamespace
discord.ui.Modal = type('Modal', (), {'__init_subclass__': lambda cls, **kw: None})
discord.ui.TextInput = type('TextInput', (), {'__init__': lambda self, *a, **k: None})
discord.ui.Select = type('Select', (), {'__init__': lambda self, *a, **k: None})
discord.ui.UserSelect = type('UserSelect', (), {'__init__': lambda self, *a, **k: None})
discord.ui.Button = type('Button', (), {'__init__': lambda self, *a, **k: None})
discord.ui.View = type('View', (), {
    '__init__': lambda self, *a, **k: None,
    'add_item': lambda self, *a, **k: None,
    'remove_item': lambda self, *a, **k: None,
})
discord.ui.button = lambda *a, **k: (lambda f: f)
discord.ButtonStyle.danger = 3
discord.ButtonStyle.success = 4
discord.opus = SimpleNamespace(is_loaded=lambda: True, load_opus=lambda *a, **k: None)
discord.VoiceChannel = object
discord.Guild = object
discord.Member = object
discord.VoiceState = object
discord.User = object
discord.app_commands.command = lambda *a, **k: (lambda f: f)

from memer.cogs.meme_admin import MemeAdmin
import memer.cogs.meme_admin as meme_admin_module


class DummyResponse:
    def is_done(self):
        return True

    async def defer(self, *args, **kwargs):
        pass


class DummyFollowup:
    async def send(self, *args, **kwargs):
        raise meme_admin_module.discord.errors.NotFound()


class DummyChannel:
    def __init__(self):
        self.sent = None

    async def send(self, content=None, **kwargs):
        self.sent = {"content": content, **kwargs}
        return SimpleNamespace(id=789)


class DummyInteraction:
    def __init__(self):
        self.response = DummyResponse()
        self.followup = DummyFollowup()
        self.channel = DummyChannel()
        self.guild = SimpleNamespace(id=123)


class DummyBot:
    def __init__(self):
        self.latency = 0.1
        self.cogs = {}

    def get_cog(self, name):
        return self.cogs.get(name)


def test_handle_ping_falls_back_to_channel_send_when_interaction_missing():
    bot = DummyBot()
    admin = MemeAdmin(bot)
    interaction = DummyInteraction()
    asyncio.run(admin.handle_ping(interaction))
    assert interaction.channel.sent["content"] == "🏓 Pong! Latency is 100ms"


def test_handle_uptime_falls_back_to_channel_send_when_interaction_missing():
    bot = DummyBot()
    admin = MemeAdmin(bot)
    admin.start_time = time.time() - 65
    interaction = DummyInteraction()
    asyncio.run(admin.handle_uptime(interaction))
    assert interaction.channel.sent["content"].startswith("⏱️ Uptime:")


def test_handle_addsubreddit_falls_back_to_channel_send_when_interaction_missing(monkeypatch):
    bot = DummyBot()
    admin = MemeAdmin(bot)
    interaction = DummyInteraction()
    name = "funny"

    monkeypatch.setattr(meme_admin_module, "add_guild_subreddit", lambda *a, **k: None)
    monkeypatch.setattr(meme_admin_module, "get_guild_subreddits", lambda *a, **k: [name])

    asyncio.run(admin.handle_addsubreddit(interaction, name, "sfw"))
    assert "✅ Added" in interaction.channel.sent["content"]


def test_handle_removesubreddit_falls_back_to_channel_send_when_interaction_missing(monkeypatch):
    bot = DummyBot()
    admin = MemeAdmin(bot)
    interaction = DummyInteraction()
    name = "funny"

    monkeypatch.setattr(meme_admin_module, "remove_guild_subreddit", lambda *a, **k: None)

    asyncio.run(admin.handle_removesubreddit(interaction, name, "sfw"))
    assert "Removed" in interaction.channel.sent["content"]


def test_handle_validatesubreddits_falls_back_to_channel_send_when_interaction_missing(monkeypatch):
    bot = DummyBot()
    admin = MemeAdmin(bot)
    interaction = DummyInteraction()

    monkeypatch.setattr(meme_admin_module, "get_guild_subreddits", lambda *a, **k: ["sub1"])

    class DummyReddit:
        async def subreddit(self, *args, **kwargs):
            pass

    class DummyMeme:
        reddit = DummyReddit()

    bot.cogs["Meme"] = DummyMeme()

    asyncio.run(admin.handle_validatesubreddits(interaction))
    assert interaction.channel.sent["content"].startswith("**SFW**")


def test_handle_reset_voice_error_falls_back_to_channel_send_when_interaction_missing(monkeypatch):
    bot = DummyBot()
    admin = MemeAdmin(bot)
    interaction = DummyInteraction()

    monkeypatch.setattr(meme_admin_module, "reset_queue", lambda *a, **k: None)
    monkeypatch.setattr(meme_admin_module, "reset_total_failures", lambda *a, **k: None)

    class DummyQueue:
        def clear(self):
            pass

    monkeypatch.setattr(meme_admin_module, "get_queue", lambda *a, **k: DummyQueue())

    asyncio.run(admin.handle_reset_voice_error(interaction))
    assert "Voice error status" in interaction.channel.sent["content"]


def test_handle_set_idle_timeout_falls_back_to_channel_send_when_interaction_missing(monkeypatch):
    bot = DummyBot()
    admin = MemeAdmin(bot)
    interaction = DummyInteraction()

    conf = {"seconds": 30}
    monkeypatch.setattr(meme_admin_module, "get_guild_config", lambda *a, **k: conf)

    asyncio.run(admin.handle_set_idle_timeout(interaction, True, 25))
    assert "Idle timeout" in interaction.channel.sent["content"]


def test_handle_toggle_gambling_falls_back_to_channel_send_when_interaction_missing():
    bot = DummyBot()
    class DummyStore:
        async def set_gambling(self, *args, **kwargs):
            pass
    class DummyGamble:
        def __init__(self):
            self.store = DummyStore()
    bot.cogs["Gamble"] = DummyGamble()
    admin = MemeAdmin(bot)
    interaction = DummyInteraction()

    asyncio.run(admin.handle_toggle_gambling(interaction, True))
    assert "Gambling has been" in interaction.channel.sent["content"]


def test_handle_setentrance_falls_back_to_channel_send_when_interaction_missing():
    bot = DummyBot()
    class DummyEntrance:
        def __init__(self):
            self.entrance_data = {}
        def get_valid_files(self):
            return ["file.mp3"]
        def save_data(self):
            pass
    bot.cogs["Entrance"] = DummyEntrance()
    admin = MemeAdmin(bot)
    interaction = DummyInteraction()
    user = SimpleNamespace(mention="@user", id=456)

    asyncio.run(admin.handle_setentrance(interaction, user, "file.mp3"))
    assert "Set `file.mp3`" in interaction.channel.sent["content"]


def test_handle_cacheinfo_falls_back_to_channel_send_when_interaction_missing():
    bot = DummyBot()
    class DummyCacheService:
        async def get_cache_info(self):
            return "stats"
    class DummyMeme:
        def __init__(self):
            self.cache_service = DummyCacheService()
    bot.cogs["Meme"] = DummyMeme()
    admin = MemeAdmin(bot)
    interaction = DummyInteraction()

    asyncio.run(admin.handle_cacheinfo(interaction))
    assert interaction.channel.sent["content"].startswith("```")


def test_handle_reloadsounds_falls_back_to_channel_send_when_interaction_missing(monkeypatch, tmp_path):
    bot = DummyBot()
    admin = MemeAdmin(bot)
    interaction = DummyInteraction()

    monkeypatch.setattr(meme_admin_module, "SOUND_FOLDER", str(tmp_path / "nosounds"))
    monkeypatch.setattr(meme_admin_module, "load_beeps", lambda: None)
    monkeypatch.setattr(meme_admin_module, "preload_audio_clips", lambda: None)
    class DummyCache:
        def clear(self):
            pass
    class DummyAudioCache:
        cache = DummyCache()
    monkeypatch.setattr(meme_admin_module, "audio_cache", DummyAudioCache())

    asyncio.run(admin.handle_reloadsounds(interaction))
    assert "Beep and entrance sounds reloaded" in interaction.channel.sent["content"]
