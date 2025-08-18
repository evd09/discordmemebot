import logging
from discord.ext import commands
from helpers.store import Store

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

    @gambling_enabled_ctx()
    @commands.hybrid_command(name="balance", description="Check your balance")
    async def balance(self, ctx: commands.Context):
        uid  = str(ctx.author.id)
        bal  = await self.store.get_balance(uid)
        name = self.bot.config.COIN_NAME
        await ctx.reply(f"💰 You have {bal} {name}.", ephemeral=bool(ctx.interaction))

    @gambling_enabled_ctx()
    @commands.hybrid_command(name="toprich", description="Top 5 richest users")
    async def toprich(self, ctx: commands.Context):
        rows = await self.store.get_top_balances(5)
        name = self.bot.config.COIN_NAME
        lines = []
        for uid, amt in rows:
            try:
                m = await ctx.guild.fetch_member(int(uid))
                display = m.display_name
            except:
                display = f"<@{uid}>"
            lines.append(f"{display}: {amt} {name}")
        await ctx.reply("\n".join(lines) or "No data yet.", ephemeral=bool(ctx.interaction))

    @gambling_enabled_ctx()
    @commands.hybrid_command(name="buy", description="Purchase a shop item")
    async def buy(self, ctx: commands.Context, item: str):
        shop = {"skipcooldown": 50, "premium-sub": 200}
        cost = shop.get(item)
        name = self.bot.config.COIN_NAME
        if cost is None:
            return await ctx.reply("❌ Unknown item.", ephemeral=bool(ctx.interaction))

        uid = str(ctx.author.id)
        bal = await self.store.get_balance(uid)
        if bal < cost:
            return await ctx.reply(f"❌ Need {cost} {name}, but have {bal}.", ephemeral=bool(ctx.interaction))

        await self.store.update_balance(uid, -cost, f"Bought {item}")
        new = await self.store.get_balance(uid)
        await ctx.reply(f"✅ Bought **{item}** for {cost} {name}. You now have {new} {name}.", ephemeral=bool(ctx.interaction))

async def setup(bot):
    await bot.add_cog(Economy(bot))