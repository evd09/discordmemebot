# cogs/audio/audio_admin.py
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

from .audio_queue import reset, get_queue
from .voice_error_manager import reset_total_failures
from .audio_events import get_guild_config

class AudioQueueAdmin(commands.Cog):
    """
    Admin commands for managing the audio queue and voice error state.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="reset_voice_error", description="Admin: Reset all voice error cooldowns for this guild.")
    async def reset_voice_error(self, interaction: discord.Interaction):
        # Permission check
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only admins can use this command.", ephemeral=True
            )
            return

        gid = interaction.guild.id
        reset(gid)
        reset_total_failures(gid)
        get_queue(gid).clear()

        await interaction.response.send_message(
            "✅ Voice error status/cooldown for this server has been reset. Try your entrance or beep again!",
            ephemeral=True
        )

    @app_commands.command(
        name="set_idle_timeout",
        description="Set or disable idle timeout for auto-leaving voice."
    )
    @app_commands.describe(
        enabled="Enable idle timeout",
        seconds="Idle seconds before leaving (ignored if disabled)"
    )
    async def set_idle_timeout(self, interaction: discord.Interaction, enabled: bool, seconds: Optional[int] = None):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Only admins can use this command.", ephemeral=True)
            return
        conf = get_guild_config(interaction.guild.id)
        conf["enabled"] = enabled
        if seconds is not None and enabled:
            conf["seconds"] = max(10, int(seconds))
        await interaction.response.send_message(
            f"✅ Idle timeout is now {'ENABLED' if enabled else 'DISABLED'}"
            + (f" ({conf['seconds']}s)" if enabled else ""),
            ephemeral=True
        )

async def setup(bot: commands.Bot):
    # Register the Cog under the correct class name
    await bot.add_cog(AudioQueueAdmin(bot))
