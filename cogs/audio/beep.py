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

class BeepPickerView(discord.ui.View):
    """Paginated beep picker. Selecting a file immediately plays it and locks the UI."""
    def __init__(self, user: discord.User, files: list[str], channel: discord.VoiceChannel, page: int = 0):
        super().__init__(timeout=30)
        self.user = user
        self.files = files
        self.channel = channel
        self.page = page
        self.page_size = 25
        self.max_page = (max(1, len(files)) - 1) // self.page_size
        self.message: discord.Message | None = None
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        self._add_select()
        self._add_pagination()

    def _add_select(self):
        # Remove any prior select
        for child in list(self.children):
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)

        start = self.page * self.page_size
        end = start + self.page_size
        options = [discord.SelectOption(label=f) for f in self.files[start:end]]

        selector = discord.ui.Select(
            placeholder="Select a beep to play",
            options=options,
            custom_id="beep_file_select",
            min_values=1,
            max_values=1,
            row=0
        )

        async def on_select(interaction: discord.Interaction):
            # Immediately play and then lock UI
            await interaction.response.defer()  # we'll edit the original message after play
            filename = interaction.data["values"][0]
            path = os.path.join(BEEP_FOLDER, filename)

            ok = await queue_audio(self.channel, interaction.user, path, 1.0, interaction, play_clip)

            # Disable everything
            for child in self.children:
                child.disabled = True

            # Update the original ephemeral message
            if ok:
                from .audio_events import signal_activity
                signal_activity(interaction.guild.id)
                text = f"🔊 Playing `{filename}`."
            else:
                text = "⚠️ Could not play right now (cooldown or voice issue). Try again in a few seconds."

            if self.message:
                await self.message.edit(content=text, view=self)
            else:
                await interaction.edit_original_response(content=text, view=self)

            # End the view lifecycle
            self.stop()

        selector.callback = on_select
        self.add_item(selector)

    def _add_pagination(self):
        # Clear existing pagers
        for child in list(self.children):
            if isinstance(child, discord.ui.Button) and getattr(child, "custom_id", None) in ("prev_page", "next_page"):
                self.remove_item(child)

        if self.max_page > 0:
            prevb = discord.ui.Button(
                label="⬅️ Prev", style=discord.ButtonStyle.secondary, custom_id="prev_page", row=1,
                disabled=(self.page == 0)
            )
            nextb = discord.ui.Button(
                label="Next ➡️", style=discord.ButtonStyle.secondary, custom_id="next_page", row=1,
                disabled=(self.page == self.max_page)
            )

            async def do_prev(interaction: discord.Interaction):
                await self._change_page(interaction, self.page - 1)

            async def do_next(interaction: discord.Interaction):
                await self._change_page(interaction, self.page + 1)

            prevb.callback = do_prev
            nextb.callback = do_next
            self.add_item(prevb)
            self.add_item(nextb)

    async def _change_page(self, interaction: discord.Interaction, new_page: int):
        self.page = max(0, min(self.max_page, new_page))
        self._add_select()
        self._add_pagination()
        await interaction.response.edit_message(
            content=f"🎛️ Pick a beep (Page {self.page+1}/{self.max_page+1})",
            view=self
        )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.message.edit(content="⏳ Picker timed out. Run `/beepselect` again.", view=self)

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

    @app_commands.command(
        name="beepselect",
        description="Browse all beep sounds with pagination. Selecting a file plays immediately."
    )
    async def beepselect(self, interaction: discord.Interaction):
        channel = getattr(interaction.user.voice, "channel", None)
        if not channel:
            return await interaction.response.send_message("❌ You must be in a voice channel.", ephemeral=True)

        files = self.get_valid_files()
        if not files:
            return await interaction.response.send_message("⚠️ No beep sounds available.", ephemeral=True)

        view = BeepPickerView(interaction.user, files, channel, page=0)
        await interaction.response.send_message("🎛️ Pick a beep:", view=view, ephemeral=True)
        view.message = await interaction.original_response()

    @commands.hybrid_command(name="listbeeps", description="List available beep sounds.")
    async def listbeeps(self, ctx: commands.Context):
        files = self.get_valid_files()
        if not files:
            # If run as a slash command
            if hasattr(ctx, "interaction") and ctx.interaction:
                return await ctx.interaction.response.send_message(
                    "⚠️ No beep sounds found.", ephemeral=True
                )
            # Classic command fallback: DM the user
            return await ctx.author.send("⚠️ No beep sounds found.")
        
        payload = "\n".join(f"`{f}`" for f in files)
        # If run as a slash command
        if hasattr(ctx, "interaction") and ctx.interaction:
            await ctx.interaction.response.send_message(payload, ephemeral=True)
        else:
            # Fallback for classic (prefix) commands: DM the user
            await ctx.author.send(payload)

    @app_commands.command(name="reloadbeeps", description="Reload beep sound files from disk (admin only).")
    async def reloadbeeps(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You must be an admin to reload beeps.", ephemeral=True)
            return
        await interaction.response.send_message("✅ Beep sounds list reloaded.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Beep(bot))
