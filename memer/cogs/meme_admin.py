# cogs/meme_admin.py
import time
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

from memer.helpers.guild_subreddits import (
    add_guild_subreddit,
    remove_guild_subreddit,
    get_guild_subreddits,
)

from .audio.audio_queue import reset as reset_queue, get_queue
from .audio.voice_error_manager import reset_total_failures
from .audio.audio_events import get_guild_config
from .audio.beep import load_beeps
from .audio.audio_player import preload_audio_clips, audio_cache


class AddSubredditModal(discord.ui.Modal, title="Add Subreddit"):
    def __init__(self, cog: "MemeAdmin"):
        super().__init__()
        self.cog = cog
        self.name = discord.ui.TextInput(label="Subreddit name")
        self.category = discord.ui.TextInput(label="Category (sfw/nsfw)")
        self.add_item(self.name)
        self.add_item(self.category)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.handle_addsubreddit(
            interaction, self.name.value, self.category.value
        )


class RemoveSubredditModal(discord.ui.Modal, title="Remove Subreddit"):
    def __init__(self, cog: "MemeAdmin"):
        super().__init__()
        self.cog = cog
        self.name = discord.ui.TextInput(label="Subreddit name")
        self.category = discord.ui.TextInput(label="Category (sfw/nsfw)")
        self.add_item(self.name)
        self.add_item(self.category)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.handle_removesubreddit(
            interaction, self.name.value, self.category.value
        )


class IdleTimeoutModal(discord.ui.Modal, title="Set Idle Timeout"):
    def __init__(self, cog: "MemeAdmin"):
        super().__init__()
        self.cog = cog
        self.enabled = discord.ui.TextInput(label="Enabled (true/false)")
        self.seconds = discord.ui.TextInput(label="Seconds", required=False)
        self.add_item(self.enabled)
        self.add_item(self.seconds)

    async def on_submit(self, interaction: discord.Interaction):
        enabled = self.enabled.value.lower() == "true"
        secs = int(self.seconds.value) if self.seconds.value else None
        await self.cog.handle_set_idle_timeout(interaction, enabled, secs)


class ToggleGamblingModal(discord.ui.Modal, title="Toggle Gambling"):
    def __init__(self, cog: "MemeAdmin"):
        super().__init__()
        self.cog = cog
        self.enable = discord.ui.TextInput(label="Enable (true/false)")
        self.add_item(self.enable)

    async def on_submit(self, interaction: discord.Interaction):
        enable = self.enable.value.lower() == "true"
        await self.cog.handle_toggle_gambling(interaction, enable)


class SetEntranceModal(discord.ui.Modal, title="Set Entrance"):
    def __init__(self, cog: "MemeAdmin"):
        super().__init__()
        self.cog = cog
        self.user_id = discord.ui.TextInput(label="User ID")
        self.filename = discord.ui.TextInput(label="Filename")
        self.add_item(self.user_id)
        self.add_item(self.filename)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user = await interaction.client.fetch_user(int(self.user_id.value))
        except Exception:
            await interaction.response.send_message(
                "Invalid user ID.", ephemeral=True
            )
            return
        await self.cog.handle_setentrance(interaction, user, self.filename.value)


class AdminView(discord.ui.View):
    def __init__(self, cog: "MemeAdmin"):
        super().__init__(timeout=60)
        self.cog = cog

    @discord.ui.button(label="Ping", style=discord.ButtonStyle.primary)
    async def ping(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.handle_ping(interaction)

    @discord.ui.button(label="Uptime", style=discord.ButtonStyle.primary)
    async def uptime(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.handle_uptime(interaction)

    @discord.ui.button(label="Add Subreddit", style=discord.ButtonStyle.secondary)
    async def add_subreddit(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(AddSubredditModal(self.cog))

    @discord.ui.button(label="Remove Subreddit", style=discord.ButtonStyle.secondary)
    async def remove_subreddit(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(RemoveSubredditModal(self.cog))

    @discord.ui.button(label="Validate Subreddits", style=discord.ButtonStyle.secondary)
    async def validate_subs(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.handle_validatesubreddits(interaction)

    @discord.ui.button(label="Reset Voice Error", style=discord.ButtonStyle.secondary)
    async def reset_voice_error(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.handle_reset_voice_error(interaction)

    @discord.ui.button(label="Set Idle Timeout", style=discord.ButtonStyle.secondary)
    async def set_idle_timeout(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(IdleTimeoutModal(self.cog))

    @discord.ui.button(label="Toggle Gambling", style=discord.ButtonStyle.secondary)
    async def toggle_gambling(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(ToggleGamblingModal(self.cog))

    @discord.ui.button(label="Set Entrance", style=discord.ButtonStyle.secondary)
    async def set_entrance(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(SetEntranceModal(self.cog))

    @discord.ui.button(label="Cache Info", style=discord.ButtonStyle.secondary)
    async def cache_info(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.handle_cacheinfo(interaction)

    @discord.ui.button(label="Reload Sounds", style=discord.ButtonStyle.danger)
    async def reload_sounds(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.handle_reloadsounds(interaction)


class MemeAdmin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time()

    @app_commands.command(name="memeadmin", description="Admin commands for MEMER")
    async def memeadmin(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only admins can use this command.", ephemeral=True
            )
            return
        view = AdminView(self)
        await interaction.response.send_message(
            "Select an admin action:", view=view, ephemeral=True
        )

    # ----- Handlers -----
    async def handle_ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"🏓 Pong! Latency is {latency_ms}ms", ephemeral=True
        )

    async def handle_uptime(self, interaction: discord.Interaction):
        elapsed = time.time() - self.start_time
        hours, rem = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(rem, 60)
        await interaction.response.send_message(
            f"⏱️ Uptime: {hours}h {minutes}m {seconds}s", ephemeral=True
        )

    async def handle_addsubreddit(
        self, interaction: discord.Interaction, name: str, category: str
    ):
        if category not in ("sfw", "nsfw"):
            await interaction.response.send_message(
                "Category must be 'sfw' or 'nsfw'.", ephemeral=True
            )
            return
        add_guild_subreddit(interaction.guild.id, name, category)
        count = len(get_guild_subreddits(interaction.guild.id, category))
        warning = ""
        if count >= 40:
            warning = (
                f"\n⚠️ **Warning:** {category.upper()} subreddits now has {count} entries. "
                "Too many may slow the bot or hit API limits!"
            )
        await interaction.response.send_message(
            f"✅ Added `{name}` to {category.upper()} subreddits for this server.{warning}",
            ephemeral=True,
        )

    async def handle_removesubreddit(
        self, interaction: discord.Interaction, name: str, category: str
    ):
        remove_guild_subreddit(interaction.guild.id, name, category)
        await interaction.response.send_message(
            f"✅ Removed `{name}` from the {category.upper()} subreddits list for this server.",
            ephemeral=True,
        )

    async def handle_validatesubreddits(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        meme_cog = self.bot.get_cog("Meme")
        if meme_cog is None:
            await interaction.followup.send("❌ Meme cog not loaded.", ephemeral=True)
            return
        results = {"sfw": [], "nsfw": []}
        for cat in ["sfw", "nsfw"]:
            subs = get_guild_subreddits(interaction.guild.id, cat)
            for sub in subs:
                try:
                    await meme_cog.reddit.subreddit(sub, fetch=True)
                    status = "✅"
                except Exception:
                    status = "❌"
                results[cat].append((sub, status))
        lines = []
        for cat in ("sfw", "nsfw"):
            valids = sum(1 for _, st in results[cat] if st == "✅")
            total = len(results[cat])
            lines.append(f"**{cat.upper()}** ({valids}/{total} valid):")
            for name, status in results[cat]:
                lines.append(f"{status} {name}")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    async def handle_reset_voice_error(self, interaction: discord.Interaction):
        gid = interaction.guild.id
        reset_queue(gid)
        reset_total_failures(gid)
        get_queue(gid).clear()
        await interaction.response.send_message(
            "✅ Voice error status/cooldown for this server has been reset. Try your entrance or beep again!",
            ephemeral=True,
        )

    async def handle_set_idle_timeout(
        self, interaction: discord.Interaction, enabled: bool, seconds: Optional[int] = None
    ):
        conf = get_guild_config(interaction.guild.id)
        conf["enabled"] = enabled
        if seconds is not None and enabled:
            conf["seconds"] = max(10, int(seconds))
        await interaction.response.send_message(
            f"✅ Idle timeout is now {'ENABLED' if enabled else 'DISABLED'}"
            + (f" ({conf['seconds']}s)" if enabled else ""),
            ephemeral=True,
        )

    async def handle_toggle_gambling(
        self, interaction: discord.Interaction, enable: bool
    ):
        gamble_cog = self.bot.get_cog("Gamble")
        if gamble_cog is None:
            await interaction.response.send_message(
                "❌ Gambling cog not loaded.", ephemeral=True
            )
            return
        guild_id = str(interaction.guild.id)
        await gamble_cog.store.set_gambling(guild_id, enable)
        status = "enabled" if enable else "disabled"
        await interaction.response.send_message(
            f"✅ Gambling has been **{status}** on this server.", ephemeral=True
        )

    async def handle_setentrance(
        self, interaction: discord.Interaction, user: discord.User, filename: str
    ):
        entrance_cog = self.bot.get_cog("Entrance")
        if entrance_cog is None:
            await interaction.response.send_message(
                "Entrance cog not loaded.", ephemeral=True
            )
            return
        files = entrance_cog.get_valid_files()
        if filename not in files:
            await interaction.response.send_message(
                "That file doesn't exist!", ephemeral=True
            )
            return
        entrance_cog.entrance_data[str(user.id)] = {"file": filename, "volume": 1.0}
        entrance_cog.save_data()
        await interaction.response.send_message(
            f"Set `{filename}` as entrance for {user.mention}.", ephemeral=True
        )

    async def handle_cacheinfo(self, interaction: discord.Interaction):
        meme_cog = self.bot.get_cog("Meme")
        if meme_cog is None:
            await interaction.response.send_message(
                "Meme cog not loaded.", ephemeral=True
            )
            return
        stats = await meme_cog.cache_service.get_cache_info()
        await interaction.response.send_message(
            f"```\n{stats}\n```", ephemeral=True
        )

    async def handle_reloadsounds(self, interaction: discord.Interaction):
        load_beeps()
        entrance_cog = self.bot.get_cog("Entrance")
        if entrance_cog and hasattr(entrance_cog, "reload_cache"):
            entrance_cog.reload_cache()
        audio_cache.cache.clear()
        preload_audio_clips()
        await interaction.response.send_message(
            "✅ Beep and entrance sounds reloaded.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MemeAdmin(bot))

