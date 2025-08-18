# cogs/audio/entrance.py
import os
import json 
import discord
import asyncio
from discord.ui import View, Select, Button
from discord.ext import commands
from discord import app_commands   
from .audio_events import signal_activity
from .audio_player import play_clip
from .audio_queue import queue_audio
from .constants import SOUND_FOLDER, ENTRANCE_DATA

class EntranceView(View):
    def __init__(self, cog, user, files, current_file, current_volume, channel, page=0):
        super().__init__(timeout=60)
        self.cog = cog
        self.user = user
        self.files = files
        self.selected_file = current_file or (files[0] if files else None)
        self.volume = current_volume
        self.channel = channel
        self.message: discord.Message = None
        self._voice_monitor_task = None

        self.page = page
        self.page_size = 25
        self.max_page = (len(files) - 1) // self.page_size

        # Add selects
        self.add_selects()

        # Add pagination buttons on row 3 if needed
        self.add_pagination()

    def add_selects(self):
        # Always remove selects if already present
        for child in list(self.children):
            if isinstance(child, Select):
                self.remove_item(child)
        start = self.page * self.page_size
        end = start + self.page_size
        current_page_files = self.files[start:end]
        file_options = [discord.SelectOption(label=f) for f in current_page_files]
        file_select = Select(placeholder="Select file", options=file_options, custom_id="file_select", row=0)
        file_select.callback = self.on_file_select
        self.add_item(file_select)

        vol_options = [discord.SelectOption(label=f"{i*10}%", value=str(i/10)) for i in range(1, 11)]
        vol_select = Select(placeholder="Select volume", options=vol_options, custom_id="volume_select", row=1)
        vol_select.callback = self.on_volume_select
        self.add_item(vol_select)

    def add_pagination(self):
        # Always remove old pagers if present
        for child in list(self.children):
            if isinstance(child, Button) and getattr(child, "custom_id", None) in ("prev_page", "next_page"):
                self.remove_item(child)
        if self.max_page > 0:
            prev = Button(
                label="⬅️ Prev", style=discord.ButtonStyle.secondary, custom_id="prev_page", row=3,
                disabled=(self.page == 0)
            )
            prev.callback = self.prev_page
            self.add_item(prev)

            nextb = Button(
                label="Next ➡️", style=discord.ButtonStyle.secondary, custom_id="next_page", row=3,
                disabled=(self.page == self.max_page)
            )
            nextb.callback = self.next_page
            self.add_item(nextb)

    async def change_page(self, interaction, new_page):
        self.page = new_page
        self.max_page = (len(self.files) - 1) // self.page_size
        self.add_selects()
        self.add_pagination()
        await interaction.response.edit_message(
            content=f"🎛️ Manage your entrance (Page {self.page+1}/{self.max_page+1}):",
            view=self
        )

    async def on_file_select(self, interaction: discord.Interaction):
        self.selected_file = interaction.data["values"][0]
        await interaction.response.edit_message(
            content=f"✅ Selected `{self.selected_file}` — Volume: {int(self.volume*100)}%", view=self
        )

    async def on_volume_select(self, interaction: discord.Interaction):
        self.volume = float(interaction.data["values"][0])
        await interaction.response.edit_message(
            content=f"✅ Volume set to {int(self.volume*100)}% — File: `{self.selected_file}`", view=self
        )

    @discord.ui.button(label="🔊 Preview", style=discord.ButtonStyle.primary, custom_id="preview", row=2)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.selected_file:
            path = os.path.join(SOUND_FOLDER, self.selected_file)
            success = await queue_audio(self.channel, interaction.user, path, self.volume, interaction, play_clip)
            if not success:
                return
            signal_activity(interaction.guild.id)
            msg = f"🎧 Previewing `{self.selected_file}` at {int(self.volume*100)}%\n(You can keep changing file/volume and preview as much as you want before saving!)"
            if self.message:
                await self.message.edit(content=msg, view=self)
            else:
                await interaction.edit_original_response(content=msg, view=self)
        else:
            await interaction.edit_original_response(content="❌ No entrance file selected.", view=self)

    @discord.ui.button(label="💾 Save", style=discord.ButtonStyle.success, custom_id="save", row=2)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        uid = str(self.user.id)
        self.cog.entrance_data[uid] = {
            "file": self.selected_file,
            "volume": self.volume
        }
        self.cog.save_data()
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.message.edit(content="✅ Entrance saved!", view=self)
        else:
            await interaction.edit_original_response(content="✅ Entrance saved!", view=self)
        self.stop()
    
    @discord.ui.button(label="❌ Remove", style=discord.ButtonStyle.danger, custom_id="remove", row=2)
    async def remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        uid = str(self.user.id)
        if uid in self.cog.entrance_data:
            del self.cog.entrance_data[uid]
            self.cog.save_data()
            msg = "🗑️ Entrance removed! Pick a new sound or Save."
        else:
            msg = "You have no entrance set. Pick a sound and Save one!"
        if self.message:
            await self.message.edit(content=msg, view=self)
        else:
            await interaction.edit_original_response(content=msg, view=self)

    async def prev_page(self, interaction: discord.Interaction):
        await self.change_page(interaction, self.page - 1)

    async def next_page(self, interaction: discord.Interaction):
        await self.change_page(interaction, self.page + 1)

    async def start_voice_monitor(self, interaction: discord.Interaction):
        await asyncio.sleep(1)
        guild = interaction.guild
        user_id = self.user.id
        while not self.is_finished():
            await asyncio.sleep(2)
            if self.is_finished() or not self.message:
                break
            member = guild.get_member(user_id)
            if not member or not member.voice or not member.voice.channel:
                for child in self.children:
                    child.disabled = True
                await self.message.edit(
                    content="❌ You are no longer in a voice channel. Please join a voice channel and run `/entrance` again to set your entrance.",
                    view=self
                )
                self.stop()
                break

    async def interaction_check(self, interaction):
        if not self._voice_monitor_task:
            self._voice_monitor_task = asyncio.create_task(self.start_voice_monitor(interaction))
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            await self.message.edit(
                content="⏳ Sorry, this session timed out. Nothing was saved. Please run `/entrance` again.",
                view=self
            )

class Entrance(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reload_cache()

    def load_data(self):
        if not os.path.exists(ENTRANCE_DATA):
            with open(ENTRANCE_DATA, "w") as f:
                json.dump({}, f)
        with open(ENTRANCE_DATA, "r") as f:
            return json.load(f)

    def save_data(self):
        with open(ENTRANCE_DATA, "w") as f:
            json.dump(self.entrance_data, f, indent=2)

    def reload_cache(self):
        self.entrance_data = self.load_data()

    def get_valid_files(self):
        return [
            f for f in os.listdir(SOUND_FOLDER)
            if f.lower().endswith((".mp3", ".wav", ".ogg", ".mp4", ".webm"))
        ]

    @app_commands.command(name="entrance", description="Manage your entrance sound.")
    async def entrance(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "❌ You must be in a voice channel.", ephemeral=True
            )
            return
        channel = interaction.user.voice.channel
        uid = str(interaction.user.id)
        user_data = self.entrance_data.get(uid, {})
        files = self.get_valid_files()
        if not files:
            await interaction.response.send_message("⚠️ No entrance sounds available.", ephemeral=True)
            return

        # Only continue if NOT on cooldown/etc.
        success = await queue_audio(channel, interaction.user, "", 1.0, interaction, play_clip)
        if not success:
            return

        signal_activity(interaction.guild.id)
        view = EntranceView(self, interaction.user, files, user_data.get("file"), user_data.get("volume", 1.0), channel, page=0)
        await interaction.response.send_message(
            "🎛️ Manage your entrance:", view=view, ephemeral=True
        )
        view.message = await interaction.original_response()

    @app_commands.command(name="myentrance", description="Show your current entrance sound.")
    async def myentrance(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        data = self.entrance_data.get(uid)
        if not data:
            await interaction.response.send_message("You don't have an entrance set. Use `/entrance` to pick one!", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Your entrance: `{data['file']}` — Volume: {int(data.get('volume', 1.0)*100)}%", ephemeral=True
        )

    async def entrance_file_autocomplete(self, interaction: discord.Interaction, current: str):
        files = self.get_valid_files()
        return [
            app_commands.Choice(name=f, value=f)
            for f in files if current.lower() in f.lower()
        ][:25]

    @app_commands.command(name="setentrance", description="(Admin) Set a user's entrance sound.")
    @app_commands.describe(user="User to set entrance for", filename="File to set")
    @app_commands.autocomplete(filename=entrance_file_autocomplete)
    async def setentrance(self, interaction: discord.Interaction, user: discord.User, filename: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You must be an admin to use this.", ephemeral=True)
            return
        files = self.get_valid_files()
        if filename not in files:
            await interaction.response.send_message("That file doesn't exist!", ephemeral=True)
            return
        self.entrance_data[str(user.id)] = {"file": filename, "volume": 1.0}
        self.save_data()
        await interaction.response.send_message(f"Set `{filename}` as entrance for {user.mention}.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Entrance(bot))

