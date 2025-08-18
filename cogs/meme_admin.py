# cogs/meme_admin.py
import time
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands

from helpers.guild_subreddits import (
    add_guild_subreddit,
    remove_guild_subreddit,
    get_guild_subreddits,
)

from .audio.audio_queue import reset as reset_queue, get_queue
from .audio.voice_error_manager import reset_total_failures
from .audio.audio_events import get_guild_config
from .audio.beep import load_beeps
from .audio.audio_player import preload_audio_clips, audio_cache


class MemeAdmin(commands.GroupCog, name="memeadmin", description="Admin commands for MEMER"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.start_time = time.time()

    # ----- Basic Info -----
    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"🏓 Pong! Latency is {latency_ms}ms", ephemeral=True
        )

    @app_commands.command(name="uptime", description="Show bot uptime")
    async def uptime(self, interaction: discord.Interaction):
        elapsed = time.time() - self.start_time
        hours, rem = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(rem, 60)
        await interaction.response.send_message(
            f"⏱️ Uptime: {hours}h {minutes}m {seconds}s", ephemeral=True
        )

    # ----- Subreddit Management -----
    @app_commands.command(name="addsubreddit", description="Add a subreddit to SFW or NSFW list.")
    @app_commands.describe(name="Subreddit name", category="sfw or nsfw")
    async def addsubreddit(self, interaction: discord.Interaction, name: str, category: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only admins can use this command.", ephemeral=True
            )
            return
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

    @app_commands.command(name="removesubreddit", description="Remove a subreddit from SFW/NSFW lists.")
    @app_commands.describe(name="Subreddit name", category="sfw or nsfw")
    async def removesubreddit(self, interaction: discord.Interaction, name: str, category: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only admins can use this command.", ephemeral=True
            )
            return
        remove_guild_subreddit(interaction.guild.id, name, category)
        await interaction.response.send_message(
            f"✅ Removed `{name}` from the {category.upper()} subreddits list for this server.",
            ephemeral=True,
        )

    @app_commands.command(name="validatesubreddits", description="Validate all current subreddits in the DB")
    async def validatesubreddits(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only admins can use this command.", ephemeral=True
            )
            return
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

    # ----- Audio Management -----
    @app_commands.command(name="reset_voice_error", description="Reset all voice error cooldowns for this guild.")
    async def reset_voice_error(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only admins can use this command.", ephemeral=True
            )
            return
        gid = interaction.guild.id
        reset_queue(gid)
        reset_total_failures(gid)
        get_queue(gid).clear()
        await interaction.response.send_message(
            "✅ Voice error status/cooldown for this server has been reset. Try your entrance or beep again!",
            ephemeral=True,
        )

    @app_commands.command(name="set_idle_timeout", description="Set or disable idle timeout for auto-leaving voice.")
    @app_commands.describe(
        enabled="Enable idle timeout",
        seconds="Idle seconds before leaving (ignored if disabled)",
    )
    async def set_idle_timeout(
        self,
        interaction: discord.Interaction,
        enabled: bool,
        seconds: Optional[int] = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only admins can use this command.", ephemeral=True
            )
            return
        conf = get_guild_config(interaction.guild.id)
        conf["enabled"] = enabled
        if seconds is not None and enabled:
            conf["seconds"] = max(10, int(seconds))
        await interaction.response.send_message(
            f"✅ Idle timeout is now {'ENABLED' if enabled else 'DISABLED'}" +
            (f" ({conf['seconds']}s)" if enabled else ""),
            ephemeral=True,
        )

    # ----- Gambling Toggle -----
    @app_commands.command(name="toggle_gambling", description="Enable or disable all /gamble subcommands in this server.")
    @app_commands.describe(enable="Enable gambling features")
    async def toggle_gambling(self, interaction: discord.Interaction, enable: bool):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only admins can use this command.", ephemeral=True
            )
            return
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

    # ----- Entrance Management -----
    async def _entrance_file_autocomplete(
        self, interaction: discord.Interaction, current: str
    ):
        entrance_cog = self.bot.get_cog("Entrance")
        if not entrance_cog:
            return []
        files = entrance_cog.get_valid_files()
        return [
            app_commands.Choice(name=f, value=f)
            for f in files if current.lower() in f.lower()
        ][:25]

    @app_commands.command(name="setentrance", description="Set a user's entrance sound.")
    @app_commands.describe(user="User to set entrance for", filename="File to set")
    @app_commands.autocomplete(filename=_entrance_file_autocomplete)
    async def setentrance(
        self, interaction: discord.Interaction, user: discord.User, filename: str
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You must be an admin to use this.", ephemeral=True
            )
            return
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

    # ----- Cache Info -----
    @app_commands.command(name="cacheinfo", description="Show cache stats for meme system")
    async def cacheinfo(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only admins can use this command.", ephemeral=True
            )
            return
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

    # ----- Reload Sounds -----
    @app_commands.command(name="reloadsounds", description="Reload beep and entrance sound data from disk (admin only).")
    async def reloadsounds(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You must be an admin to reload sounds.", ephemeral=True
            )
            return
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

