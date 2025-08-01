# cogs/audio/beep.py
import os
import random
import logging
import discord
from discord.ext import commands
from discord import app_commands
from .audio_player import play_clip  # does NOT manage cooldowns/locks
from .audio_queue import queue_audio  # all logic for cooldown/locks/4006 is here
from logger_setup import setup_logger

logger = setup_logger("beep", "beep.log")
BEEP_FOLDER = "./sounds/beeps"

async def _beep_autocomplete(interaction: discord.Interaction, current: str):
    files = [f for f in os.listdir(BEEP_FOLDER) if f.endswith((".mp3", ".wav", ".ogg"))]
    return [
        app_commands.Choice(name=f, value=f)
        for f in files if current.lower() in f.lower()
    ][:25]

class Beep(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_valid_files(self):
        return [f for f in os.listdir(BEEP_FOLDER) if f.endswith((".mp3", ".wav", ".ogg"))]

    @app_commands.command(name="beep", description="Play a random beep sound.")
    async def beep(self, interaction: discord.Interaction):
        # Defer so we can edit the message later (always ephemeral)
        await interaction.response.defer(ephemeral=True)
        channel = getattr(interaction.user.voice, "channel", None)
        if not channel:
            await interaction.edit_original_response(content="❌ You must be in a voice channel.")
            return

        files = self.get_valid_files()
        if not files:
            await interaction.edit_original_response(content="⚠️ No beep sounds available.")
            return

        selected = random.choice(files)
        path = os.path.join(BEEP_FOLDER, selected)
        # Always go through queue_audio, not play_clip!
        await queue_audio(channel, interaction.user, path, 1.0, interaction, play_clip)
        from .audio_events import signal_activity
        signal_activity(interaction.guild.id)
        await interaction.edit_original_response(content=f"🔊 Beep! Playing `{selected}`.")

    @app_commands.command(name="beepfile", description="Play a specific beep sound by filename.")
    @app_commands.describe(filename="Beep file to play")
    @app_commands.autocomplete(filename=_beep_autocomplete)
    async def beepfile(self, interaction: discord.Interaction, filename: str):
        await interaction.response.defer(ephemeral=True)
        channel = getattr(interaction.user.voice, "channel", None)
        if not channel:
            await interaction.edit_original_response(content="❌ You must be in a voice channel.")
            return

        path = os.path.join(BEEP_FOLDER, filename)
        if not os.path.exists(path):
            await interaction.edit_original_response(content="❌ File not found.")
            return

        await queue_audio(channel, interaction.user, path, 1.0, interaction, play_clip)
        from .audio_events import signal_activity
        signal_activity(interaction.guild.id)
        await interaction.edit_original_response(content=f"🔊 Playing `{filename}` beep sound.")

    @commands.hybrid_command(name="listbeeps", description="List available beep sounds.")
    async def listbeeps(self, ctx: commands.Context):
        files = self.get_valid_files()
        if not files:
            return await ctx.send("⚠️ No beep sounds found.", ephemeral=True)
        payload = "\n".join(f"`{f}`" for f in files)
        if hasattr(ctx, "respond"):
            await ctx.respond(payload, ephemeral=True)
        else:
            await ctx.send(payload)

    @app_commands.command(name="reloadbeeps", description="Reload beep sound files from disk (admin only).")
    async def reloadbeeps(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You must be an admin to reload beeps.", ephemeral=True)
            return
        await interaction.response.send_message("✅ Beep sounds list reloaded.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Beep(bot))
