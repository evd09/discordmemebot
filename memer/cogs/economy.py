import logging
import discord
from discord.ext import commands
from memer.helpers.store import Store

log = logging.getLogger(__name__)

def gambling_enabled_ctx():
    """A check decorator for commands.Context to ensure gambling is on."""
    async def predicate(ctx: commands.Context):
        # Always allow in DMs or if no guild context
        if not ctx.guild:
            return True

        guild_id = str(ctx.guild.id)
        if not await ctx.cog.store.is_gambling_enabled(guild_id):
            raise commands.CheckFailure("❌ Gambling is disabled in this server.")
        return True
    return commands.check(predicate)

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot   = bot
        self.store = Store()
        # initialize DB tables
        bot.loop.create_task(self.store.init())

    def cog_unload(self):
        self.bot.loop.create_task(self.store.close())

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context):
        # only care about our two meme commands
        if ctx.command.name not in ("meme", "nsfwmeme"):
            return

        # skip if run in DMs
        if not ctx.guild:
            return

        # bail out entirely if gambling is disabled in this guild
        guild_id = str(ctx.guild.id)
        if not await self.store.is_gambling_enabled(guild_id):
            return

        # if the command flagged “no reward”, bail out
        if getattr(ctx, "_no_reward", False):
            return

        uid  = str(ctx.author.id)
        name = self.bot.config.COIN_NAME
        parts: list[str] = []

        # 1) daily bonus
        if await self.store.try_daily_bonus(uid, self.bot.config.DAILY_BONUS):
            parts.append(f"🎉 Daily bonus: +{self.bot.config.DAILY_BONUS} {name}")

        # 2) base reward
        await self.store.update_balance(uid, self.bot.config.BASE_REWARD, f"Used /{ctx.command.name}")
        parts.append(f"💰 +{self.bot.config.BASE_REWARD} {name} for using /{ctx.command.name}")

        # 3) keyword bonus (only if we didn’t fallback)
        keyword = ctx.kwargs.get("keyword")
        if keyword and not getattr(ctx, "_chosen_fallback", False):
            await self.store.update_balance(uid, self.bot.config.KEYWORD_BONUS, f"Bonus for '{keyword}'")
            parts.append(f"✨ +{self.bot.config.KEYWORD_BONUS} {name} bonus for keyword `{keyword}`")

        # 4) send one combined ephemeral message
        if parts:
            # ephemeral only works on slash; hybrid will fall back to normal reply
            if ctx.interaction:
                await ctx.reply("\n".join(parts), ephemeral=True)
            else:
                await ctx.reply("\n".join(parts))

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        # catch our own check failures and inform the user
        if isinstance(error, commands.CheckFailure):
            return await ctx.reply(str(error), ephemeral=True)
        # otherwise let the default handler run
        # (do not re-raise here)

    async def _send_balance(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        bal = await self.store.get_balance(uid)
        name = self.bot.config.COIN_NAME
        await interaction.response.send_message(f"💰 You have {bal} {name}.", ephemeral=True)

    async def _buy_item(self, interaction: discord.Interaction, item: str):
        shop = {"skipcooldown": 50, "premium-sub": 200}
        cost = shop.get(item)
        name = self.bot.config.COIN_NAME
        if cost is None:
            await interaction.response.send_message("❌ Unknown item.", ephemeral=True)
            return

        uid = str(interaction.user.id)
        bal = await self.store.get_balance(uid)
        if bal < cost:
            await interaction.response.send_message(f"❌ Need {cost} {name}, but have {bal}.", ephemeral=True)
            return

        await self.store.update_balance(uid, -cost, f"Bought {item}")
        new = await self.store.get_balance(uid)
        await interaction.response.send_message(
            f"✅ Bought **{item}** for {cost} {name}. You now have {new} {name}.",
            ephemeral=True,
        )

    class StoreView(discord.ui.View):
        def __init__(self, cog: "Economy", author_id: int):
            super().__init__()
            self.cog = cog
            self.author_id = author_id

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self.author_id:
                await interaction.response.send_message("❌ This store isn't for you.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="Balance", style=discord.ButtonStyle.primary)
        async def balance_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.cog._send_balance(interaction)

        @discord.ui.button(label="Buy Skipcooldown (50)", style=discord.ButtonStyle.secondary)
        async def buy_skip(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.cog._buy_item(interaction, "skipcooldown")

        @discord.ui.button(label="Buy Premium-Sub (200)", style=discord.ButtonStyle.secondary)
        async def buy_premium(self, interaction: discord.Interaction, button: discord.ui.Button):
            await self.cog._buy_item(interaction, "premium-sub")

    @gambling_enabled_ctx()
    @commands.hybrid_command(name="store", description="Open the store interface")
    async def store_cmd(self, ctx: commands.Context):
        view = self.StoreView(self, ctx.author.id)
        await ctx.reply("🛒 Welcome to the store!", view=view, ephemeral=bool(ctx.interaction))

async def setup(bot):
    await bot.add_cog(Economy(bot))
