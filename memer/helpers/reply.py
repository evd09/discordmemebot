import discord

async def safe_reply(interaction: discord.Interaction, **kwargs):
    """Safely reply to an interaction.

    If the interaction hasn't been responded to, it will be deferred.
    The response is attempted via ``followup.send`` and falls back to
    ``channel.send`` if the interaction has expired.
    """
    if not interaction.response.is_done():
        try:
            await interaction.response.defer(ephemeral=kwargs.get("ephemeral", False))
        except discord.errors.NotFound:
            pass
    try:
        return await interaction.followup.send(**kwargs)
    except discord.errors.NotFound:
        kwargs.pop("ephemeral", None)
        if getattr(interaction, "channel", None):
            return await interaction.channel.send(**kwargs)
        return None
