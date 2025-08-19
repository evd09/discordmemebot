# File: cogs/meme.py
import os
import random
import asyncio
import logging
import json

# 🔐 Define the logger IMMEDIATELY after importing it
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

from datetime import datetime
from typing import Optional
from asyncprawcore import NotFound
import asyncpraw
from memer.helpers.guild_subreddits import (
    get_guild_subreddits,
    DEFAULTS,
)
from memer.meme_stats import (
    update_stats,
    track_reaction,
    get_dashboard_stats,
    get_reactions_for_message,
    get_top_reacted_memes,
)
from memer.helpers.store import Store
from collections import defaultdict, deque
import discord
from discord import Embed
from discord.ext import commands, tasks
from memer.helpers.meme_utils import (
    get_image_url,
    send_meme,
    get_rxddit_url,
    extract_post_data,
)
from memer.helpers.meme_cache_service import MemeCacheService
from memer.helpers.db import get_recent_post_ids, register_meme_message
# Refactored utilities and cache
from memer.reddit_meme import (
    fetch_meme      as fetch_meme_util,
    simple_random_meme,
    NoMemeFoundError,
    start_warmup,
    stop_warmup,
    WARM_CACHE,
)
from memer.helpers.reddit_config import start_observer, stop_observer

class Meme(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        try:
            log.info("Meme cog initializing...")
        except Exception as e:
            print("[MEME COG INIT ERROR]", e)
        self.recent_ids = defaultdict(lambda: deque(maxlen=200))
        log.info("MemeBot initialized at %s", datetime.utcnow())

        # Reddit client
        self.reddit = asyncpraw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent="MemeBot (by u/YourUsername)"
        )
        # Inside your bot or cog class init/setup
        self.cache_service = MemeCacheService(
            reddit=self.reddit,
            config=getattr(bot.config, "MEME_CACHE", {})
        )
        try:
            log.info("Reddit + Cache initialized")
        except Exception as e:
            print("[CACHE INIT ERROR]", e)

        # Start prune task
        self._prune_cache.start()
        # Kick off warmup immediately
        subs = DEFAULTS["sfw"] + DEFAULTS["nsfw"]
        log.debug("Scheduling warmup for subs: %s", subs)
        asyncio.create_task(start_warmup(self.reddit, subs))
        start_observer()

    def cog_unload(self):
        self._prune_cache.cancel()
        asyncio.create_task(self.cache_service.close())
        asyncio.create_task(stop_warmup())
        stop_observer()
        log.info("MemeBot unloaded; warmup stopped and observer shut down.")

    @tasks.loop(seconds=60)
    async def _prune_cache(self):
        log.debug("_prune_cache: guilds=%s", list(self.recent_ids.keys()))

    @commands.Cog.listener()
    async def on_ready(self):
        log.info("on_ready: bot is ready")
        await self.cache_service.init()

    async def _send_cached(
        self,
        ctx: commands.Context,
        post_dict: dict,
        keyword: str,
        via: str,
        nsfw: bool,
    ):
        """
        Send a single cached meme (post_dict) and update stats.
        ``via`` documents where the meme came from (e.g. ``RAM``, ``DISK``,
        ``WARM CACHE`` or ``LOCAL``).
        """
        # figure out a permalink
        permalink = post_dict.get("permalink")
        if not permalink:
            # e.g. /r/memes/comments/abcd1234
            permalink = f"/r/{post_dict['subreddit']}/comments/{post_dict['post_id']}"
        
        # 1️⃣ Build embed
        embed = Embed(
            title=post_dict["title"],
            url=f"https://reddit.com{permalink}",
            description=f"r/{post_dict['subreddit']} • u/{post_dict.get('author', '[deleted]')}"
        )
        embed.set_footer(text=f"via {via}")

        # 2️⃣ Resolve URLs
        raw_url   = post_dict.get("media_url") or post_dict.get("url")
        embed_url = get_rxddit_url(raw_url)

        # 3️⃣ Send
        sent = await send_meme(ctx, url=embed_url, embed=embed)

        # 4️⃣ Stats
        register_meme_message(
            sent.id,
            ctx.channel.id,
            ctx.guild.id,
            f"https://reddit.com{permalink}",
            post_dict["title"]
        )
        await update_stats(ctx.author.id, keyword or "", post_dict["subreddit"], nsfw=nsfw)

    async def _try_cache_or_local(self, ctx, nsfw: bool, keyword: Optional[str]) -> bool:
        """Attempt to send a meme from warm cache or local fallback files.

        Returns True if a meme was sent, False otherwise.
        """
        subs = get_guild_subreddits(ctx.guild.id, "nsfw" if nsfw else "sfw")

        # 1️⃣ Try WARM_CACHE buffers first
        random.shuffle(subs)
        for listing in ("hot", "new"):
            for sub in subs:
                key = f"{sub}_{listing}"
                buf = WARM_CACHE.get(key)
                if buf:
                    while buf:
                        post = buf.pop()
                        if not post:
                            continue
                        data = extract_post_data(post)
                        await self._send_cached(ctx, data, keyword or "", "WARM CACHE", nsfw)
                        return True

        # 2️⃣ Local fallback bundle
        config = getattr(self.bot.config, "MEME_CACHE", {})
        folder = config.get("fallback_dir")
        if folder:
            fname = "nsfw.json" if nsfw else "sfw.json"
            path = os.path.join(folder, fname)
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        posts = json.load(f)
                except Exception:
                    posts = []
                if posts:
                    post_dict = random.choice(posts)
                    await self._send_cached(ctx, post_dict, keyword or "", "LOCAL", nsfw)
                    return True

        return False

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        await track_reaction(reaction.message.id, user.id, str(reaction.emoji))
        log.debug("Tracked reaction %s on %s by %s", reaction.emoji, reaction.message.id, user.id)

    @commands.hybrid_command(
        name="meme",
        description="Fetch a SFW meme (title contains your keyword, or random if none found)"
    )
    async def meme(self, ctx, keyword: Optional[str] = None):
        log.info("/meme invoked: guild=%s user=%s keyword=%s",
                 ctx.guild.id, ctx.author.id, keyword)

        # ─── Safe defer ──────────────────────────────────────
        try:
            await ctx.defer()
        except discord.errors.NotFound:
            pass

        # ─── Pipeline + cache ────────────────────────────────
        result = await fetch_meme_util(
            reddit=self.reddit,
            subreddits=get_guild_subreddits(ctx.guild.id, "sfw"),
            cache_mgr=self.cache_service.cache_mgr,
            keyword=keyword,
            nsfw=False,
        )
        post = getattr(result, "post", None)

        # did we actually find something via keyword?
        got_keyword = bool(keyword and result.picked_via in ("cache", "live"))

        # ─── Final fallback: truly random ────────────────────
        if not post:
            all_subs = get_guild_subreddits(ctx.guild.id, "sfw")
            rand_sub = random.choice(all_subs)
            post = await simple_random_meme(self.reddit, rand_sub)
            if not post:
                if await self._try_cache_or_local(ctx, nsfw=False, keyword=keyword):
                    return
                ctx._no_reward = True
                return await ctx.interaction.followup.send(
                    "✅ No memes found—try again later!", ephemeral=True
                )
            # fake a result object for footer
            result = type("F", (), {})()
            result.source_subreddit = rand_sub
            result.picked_via       = "random"

        # ─── Avoid recently sent posts ─────────────────────
        recent_ids = await get_recent_post_ids(ctx.channel.id, limit=20)
        attempts = 0
        all_subs = get_guild_subreddits(ctx.guild.id, "sfw")
        while post and post.id in recent_ids and attempts < 5:
            rand_sub = random.choice(all_subs)
            post = await simple_random_meme(self.reddit, rand_sub)
            if not post:
                attempts += 1
                continue
            result.source_subreddit = rand_sub
            result.picked_via = "random"
            attempts += 1
        if not post or post.id in recent_ids:
            if await self._try_cache_or_local(ctx, nsfw=False, keyword=keyword):
                return
            ctx._no_reward = True
            return await ctx.interaction.followup.send(
                "✅ No fresh memes right now—try again later!", ephemeral=True
            )

        # ─── BUILD EMBED ─────────────────────────────────────
        embed = Embed(
            title=post.title,
            url=f"https://reddit.com{post.permalink}",
            description=f"r/{result.source_subreddit} • u/{post.author}"
        )
        embed.set_footer(text=f"via {result.picked_via.upper()}")

        raw_url   = get_image_url(post)
        embed_url = get_rxddit_url(raw_url)

        # only apologize if they asked for keyword but got no hits
        content = None
        if keyword and not got_keyword:
            content = (
                f"🔍 Sorry, I couldn’t find any memes containing `{keyword}`—"
                " here is a random one (random fallback)"
            )
            ctx._chosen_fallback = True

        try:
            sent = await send_meme(ctx, url=embed_url, content=content, embed=embed)
            log.info("✅ send_meme succeeded message_id=%s", sent.id)
        except Exception:
            log.exception("Error in send_meme")
            ctx._no_reward = True
            return await ctx.interaction.followup.send(
                "❌ Error sending meme.", ephemeral=True
            )

        # ─── STATS & DEDUP ────────────────────────────────────
        register_meme_message(
            sent.id,
            ctx.channel.id,
            ctx.guild.id,
            f"https://reddit.com{post.permalink}",
            post.title,
            post_id=post.id
        )
        await update_stats(ctx.author.id, keyword or "", result.source_subreddit, nsfw=False)

    @commands.hybrid_command(
        name="nsfwmeme",
        description="Fetch a NSFW meme (title contains your keyword, or random if none found)"
    )
    async def nsfwmeme(self, ctx, keyword: Optional[str] = None):
        log.info("/nsfwmeme invoked: guild=%s user=%s keyword=%s",
                 ctx.guild.id, ctx.author.id, keyword)

        # ─── NSFW channel check ───────────────────────────────
        if not ctx.channel.is_nsfw():
            ctx._no_reward = True
            return await ctx.interaction.response.send_message(
                "🔞 You can only use NSFW memes in NSFW channels.",
                ephemeral=True
            )

        # ─── Safe defer ──────────────────────────────────────
        try:
            await ctx.defer()
        except discord.errors.NotFound:
            pass

        # ─── Pipeline + cache ────────────────────────────────
        result = await fetch_meme_util(
            reddit=self.reddit,
            subreddits=get_guild_subreddits(ctx.guild.id, "nsfw"),
            cache_mgr=self.cache_service.cache_mgr,
            keyword=keyword,
            nsfw=True,
        )
        post = getattr(result, "post", None)

        # did we actually find something via keyword?
        got_keyword = bool(keyword and result.picked_via in ("cache", "live"))

        # ─── Final fallback: truly random ────────────────────
        if not post:
            all_subs = get_guild_subreddits(ctx.guild.id, "nsfw")
            rand_sub = random.choice(all_subs)
            post = await simple_random_meme(self.reddit, rand_sub)
            if not post:
                if await self._try_cache_or_local(ctx, nsfw=True, keyword=keyword):
                    return
                ctx._no_reward = True
                return await ctx.interaction.followup.send(
                    "✅ No NSFW memes right now—try again later!", ephemeral=True
                )
            result = type("F", (), {})()
            result.source_subreddit = rand_sub
            result.picked_via       = "random"

        # ─── Avoid recently sent posts ─────────────────────
        recent_ids = await get_recent_post_ids(ctx.channel.id, limit=20)
        attempts = 0
        all_subs = get_guild_subreddits(ctx.guild.id, "nsfw")
        while post and post.id in recent_ids and attempts < 5:
            rand_sub = random.choice(all_subs)
            post = await simple_random_meme(self.reddit, rand_sub)
            if not post:
                attempts += 1
                continue
            result.source_subreddit = rand_sub
            result.picked_via = "random"
            attempts += 1
        if not post or post.id in recent_ids:
            if await self._try_cache_or_local(ctx, nsfw=True, keyword=keyword):
                return
            ctx._no_reward = True
            return await ctx.interaction.followup.send(
                "✅ No fresh NSFW memes right now—try again later!", ephemeral=True
            )

        # ─── BUILD EMBED ─────────────────────────────────────
        embed = Embed(
            title=post.title,
            url=f"https://reddit.com{post.permalink}",
            description=f"r/{result.source_subreddit} • u/{post.author}"
        )
        embed.set_footer(text=f"via {result.picked_via.upper()}")

        raw_url   = get_image_url(post)
        embed_url = get_rxddit_url(raw_url)

        # only apologize if they asked for keyword but got no hits
        content = None
        if keyword and not got_keyword:
            content = (
                f"🔍 Sorry, I couldn’t find any NSFW memes containing `{keyword}`—"
                " here is a random one (random fallback)"
            )
            ctx._chosen_fallback = True

        try:
            sent = await send_meme(ctx, url=embed_url, content=content, embed=embed)
            log.info("✅ NSFW send_meme succeeded message_id=%s", sent.id)
        except Exception:
            log.exception("Error in send_meme")
            ctx._no_reward = True
            return await ctx.interaction.followup.send(
                "❌ Error sending NSFW meme.", ephemeral=True
            )

        # ─── STATS & DEDUP ────────────────────────────────────
        register_meme_message(
            sent.id,
            ctx.channel.id,
            ctx.guild.id,
            f"https://reddit.com{post.permalink}",
            post.title,
            post_id=post.id
        )
        await update_stats(ctx.author.id, keyword or "", result.source_subreddit, nsfw=True)

    @commands.hybrid_command(name="r_", description="Fetch a meme from a specific subreddit")
    async def r_(self, ctx: commands.Context, subreddit: str, keyword: Optional[str] = None):
        log.info("/r_ invoked: guild=%s user=%s subreddit=%s keyword=%s",
                 ctx.guild.id, ctx.author.id, subreddit, keyword)

        # 1) Defer to give us 3s
        await ctx.defer()

        # 2) Lookup subreddit
        try:
            sub = await self.reddit.subreddit(subreddit, fetch=True)
        except NotFound:
            return await ctx.reply(f"❌ Could not find subreddit `{subreddit}`.", ephemeral=True)

        # 3) Fetch via pipeline (or random fallback)
        post = None
        random_fallback = False

        try:
            result = await fetch_meme_util(
                reddit=self.reddit,
                subreddits=[sub],
                keyword=keyword,
                cache_mgr=self.cache_service.cache_mgr,
                nsfw=bool(getattr(sub, "over18", False)),
            )
            post = getattr(result, "post", None) if result else None

            # If nothing found, do a true random fallback from that subreddit
            if not post:
                log.info("No post found via keyword, trying random fallback in r/%s", subreddit)
                post = await simple_random_meme(self.reddit, subreddit)
                if not post:
                    log.info("No random meme found for r/%s, sending fail message.", subreddit)
                    if ctx.interaction:
                        return await ctx.interaction.followup.send(
                            f"✅ No memes found in r/{subreddit} right now—try again later!",
                            ephemeral=True
                        )
                    return await ctx.send(
                        f"✅ No memes found in r/{subreddit} right now—try again later!"
                    )
                # Build a result-like object for footer display
                result = type("F", (), {})()
                result.source_subreddit = subreddit
                result.picked_via       = "random"

            recent_ids = await get_recent_post_ids(ctx.channel.id, limit=20)
            attempts = 0
            while post and post.id in recent_ids and attempts < 5:
                log.debug("🚫 recently sent, trying another post")
                post = await simple_random_meme(self.reddit, subreddit)
                if post:
                    result.source_subreddit = subreddit
                    result.picked_via = "random"
                attempts += 1

            if not post or post.id in recent_ids:
                if ctx.interaction:
                    return await ctx.interaction.followup.send(
                        f"✅ No fresh posts in r/{subreddit} right now—try again later!",
                        ephemeral=True
                    )
                return await ctx.send(
                    f"✅ No fresh posts in r/{subreddit} right now—try again later!"
                )

            raw_url = get_image_url(post)
            if raw_url.endswith(('.mp4', '.webm')):
                embed_url = get_rxddit_url(raw_url)  # use proxy for videos
            else:
                embed_url = raw_url  # original for images

            embed = Embed(
                title=post.title[:256],
                url=f"https://reddit.com{post.permalink}",
                description=f"r/{result.source_subreddit} • u/{post.author}"
            )
            embed.set_footer(text=f"via {result.picked_via.upper()}")

            content = None
            if getattr(result, "picked_via", None) == "random":
                content = "here is a random one (random fallback)"

            sent = await send_meme(
                ctx,
                url=embed_url,
                content=content,
                embed=embed
            )

            register_meme_message(
                sent.id,
                ctx.channel.id,
                ctx.guild.id,
                f"https://reddit.com{post.permalink}",
                post.title,
                post_id=post.id
            )
            await update_stats(ctx.author.id, keyword or "", result.source_subreddit, nsfw=False)
        except Exception as e:
            log.error(f"Error in /r_ command: {e}", exc_info=True)
            if ctx.interaction:
                await ctx.interaction.followup.send(
                    "❌ Error fetching meme from subreddit.", ephemeral=True
                )
            else:
                await ctx.send("❌ Error fetching meme from subreddit.")

    @commands.hybrid_command(name="dashboard", description="Show a stats dashboard")
    async def dashboard(self, ctx):
        """Display total memes, top users, subreddits, and keywords."""
        try:
            all_stats = await get_dashboard_stats()
            total = all_stats.get("total_memes", 0)
            nsfw = all_stats.get("nsfw_memes", 0)
            users = all_stats.get("user_counts", {})
            subs = all_stats.get("subreddit_counts", {})
            kws = all_stats.get("keyword_counts", {})

            # Get top users, subreddits, keywords
            top_users = sorted(users.items(), key=lambda x: x[1], reverse=True)[:5]
            top_subs = sorted(subs.items(), key=lambda x: x[1], reverse=True)[:5]
            top_kws = sorted(kws.items(), key=lambda x: x[1], reverse=True)[:5]

            # Top reacted memes
            reacted = await get_top_reacted_memes(5)

            # Top richest users (economy)
            store = Store()
            await store.init()
            rich_rows = await store.get_top_balances(5)
            await store.close()

            # Format user lines with usernames if possible, else show mention
            user_lines = []
            for uid, count in top_users:
                try:
                    member = ctx.guild.get_member(int(uid)) or await ctx.guild.fetch_member(int(uid))
                    name = member.display_name
                except Exception:
                    name = f"<@{uid}>"
                user_lines.append(f"{name}: {count}")
            user_lines = "\n".join(user_lines) or "None"

            sub_lines = "\n".join(f"{s}: {c}" for s, c in top_subs) or "None"
            kw_lines = "\n".join(f"{k}: {c}" for k, c in top_kws) or "None"

            react_lines = []
            for msg_id, url, title, guild_id, channel_id, count in reacted:
                msg_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{msg_id}"
                react_lines.append(f"[{title}]({msg_url}) — {count}")
            react_lines = "\n".join(react_lines) or "None"

            coin_name = getattr(self.bot.config, "COIN_NAME", "coins")
            rich_lines = []
            for uid, amt in rich_rows:
                try:
                    member = ctx.guild.get_member(int(uid)) or await ctx.guild.fetch_member(int(uid))
                    name = member.display_name
                except Exception:
                    name = f"<@{uid}>"
                rich_lines.append(f"{name}: {amt} {coin_name}")
            rich_lines = "\n".join(rich_lines) or "None"

            # Build the embed
            embed = discord.Embed(
                title="📊 MemeBot Dashboard",
                color=discord.Color.blurple(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="😂 Total Memes",    value=str(total),      inline=True)
            embed.add_field(name="🔞 NSFW Memes",     value=str(nsfw),       inline=True)
            embed.add_field(name="\u200b",            value="\u200b",        inline=True)  # spacer
            embed.add_field(name="🥇 Top Users",      value=user_lines,      inline=False)
            embed.add_field(name="🌐 Top Subreddits", value=sub_lines,       inline=False)
            embed.add_field(name="🔍 Top Keywords",   value=kw_lines,        inline=False)
            embed.add_field(name="🔥 Top Reactions",  value=react_lines,     inline=False)
            embed.add_field(name="💰 Richest Users",  value=rich_lines,      inline=False)

            await ctx.reply(embed=embed, ephemeral=True)

        except Exception:
            log.error("dashboard command error", exc_info=True)
            await ctx.reply("❌ Error generating dashboard.", ephemeral=True)

    @commands.hybrid_command(name="help", description="Show all available commands")
    async def help(self, ctx: commands.Context):
        """Show a list of available bot commands."""
        embed = discord.Embed(
            title="🤖 Bot Commands",
            description="Here's what I can do:",
            color=discord.Color.blurple()
        )

        # ---------------- User Commands ----------------
        user_cmds = [
            "`/store` - Check balance or buy items",
            "`/meme [keyword]` - Fetch a SFW meme",
            "`/nsfwmeme [keyword]` - Fetch a NSFW meme",
            "`/r_ <subreddit> [keyword]` - Fetch from a specific subreddit",
            "`/dashboard` - Show stats and leaderboards",
            "`/gamble help` - Show all available gambling games",
            "`/gamble list` - List your recent bets and game stats",
            "`/entrance` - Set or preview your entrance sound (full UI)",
            "`/beeps` - Play a random beep or choose one",
        ]
        embed.add_field(name="User Commands", value="\n".join(user_cmds), inline=False)

        # ---------------- Admin Commands ----------------
        admin_cmds = [
            "`/memeadmin ping` - Check bot latency",
            "`/memeadmin uptime` - Show bot uptime",
            "`/memeadmin addsubreddit` - Add a subreddit to SFW or NSFW list",
            "`/memeadmin removesubreddit` - Remove a subreddit from SFW or NSFW list",
            "`/memeadmin validatesubreddits` - Validate current subreddits",
            "`/memeadmin reset_voice_error` - Reset voice error cooldowns",
            "`/memeadmin set_idle_timeout` - Set or disable idle timeout for voice",
            "`/memeadmin toggle_gambling` - Enable or disable all gambling features",
            "`/memeadmin setentrance` - Set a user's entrance sound",
            "`/memeadmin cacheinfo` - Show the current audio cache stats",
        ]
        embed.add_field(name="Admin Commands", value="\n".join(admin_cmds), inline=False)

        # ---------------- Dynamic Info ----------------
        sfw = ", ".join(get_guild_subreddits(ctx.guild.id, "sfw")) or "None"
        nsfw = ", ".join(get_guild_subreddits(ctx.guild.id, "nsfw")) or "None"
        embed.add_field(
            name="Loaded Subreddits",
            value=f"**SFW:** {sfw}\n**NSFW:** {nsfw}",
            inline=False,
        )

        beep_cog = self.bot.get_cog("Beep")
        if beep_cog:
            beeps = ", ".join(beep_cog.get_valid_files()) or "None"
            embed.add_field(
                name="Available Beeps",
                value=beeps,
                inline=False,
            )

        await ctx.reply(embed=embed, ephemeral=True)

    @help.error
    async def help_error(self, ctx, error):
        log.error("Help command error", exc_info=error)
        await ctx.reply("❌ Could not show help. Please try again later.", ephemeral=True)


    @meme.error
    async def meme_error(self, ctx, error):
        # this will catch exceptions from your meme() command
        log.error("Error in /meme command", exc_info=error)
        # if you already deferred, send via followup
        try:
            await ctx.interaction.followup.send(
                "❌ Oops—something went wrong fetching your meme. Please try again later.",
                ephemeral=True
            )
        except Exception:
            # if followup fails, fall back to a response
            await ctx.interaction.response.send_message(
                "❌ Oops—something went wrong!",
                ephemeral=True
            )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Meme(bot))
