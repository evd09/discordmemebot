# File: cogs/meme.py
import os
import random
import asyncio
import time
import logging

# 🔐 Define the logger IMMEDIATELY after importing it
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

from datetime import datetime
from typing import Optional
from asyncprawcore import NotFound
import asyncpraw
from helpers.guild_subreddits import (
    add_guild_subreddit,
    remove_guild_subreddit,
    get_guild_subreddits,
    DEFAULTS,
)
from meme_stats import (
    update_stats,
    track_reaction,
    get_dashboard_stats,
    get_top_users,
    get_top_keywords,
    get_top_subreddits,
    get_reactions_for_message,
    get_top_reacted_memes,
)
from collections import defaultdict, deque
import discord
from discord import Embed
from discord.ext import commands, tasks
from helpers.meme_utils import get_image_url, send_meme, get_rxddit_url
from helpers.meme_cache_service import MemeCacheService
from helpers.db import get_recent_post_ids, register_meme_message
# Refactored utilities and cache
from reddit_meme import (
    fetch_meme      as fetch_meme_util,
    simple_random_meme,
    NoMemeFoundError,
    start_warmup,
    stop_warmup,
    observer,
    WARM_CACHE,
)

class Meme(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        try:
            log.info("Meme cog initializing...")
        except Exception as e:
            print("[MEME COG INIT ERROR]", e)
        self.start_time = time.time()
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

    def cog_unload(self):
        self._prune_cache.cancel()
        asyncio.create_task(self.cache_service.close())
        asyncio.create_task(stop_warmup())
        observer.stop()
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
        via: str
    ):
        """
        Send a single cached meme (post_dict) and update stats.
        via is one of "RAM" or "DISK".
        """
        # figure out a permalink
        permalink = post_dict.get("permalink")
        if not permalink:
            # e.g. /r/memes/comments/abcd1234
            permalink = f"/r/{post_dict['subreddit']}/comments/{post_dict['post_id']}"
        
        # 1️⃣ Build embed
        embed = Embed(
            title=post_dict["title"],
            url=f"https://reddit.com{permalink}"
        )
        embed.set_footer(text=f"r/{post_dict['subreddit']} • via {via}")

        # 2️⃣ Resolve URLs
        raw_url   = post_dict.get("media_url") or post_dict.get("url")
        embed_url = get_rxddit_url(raw_url)

        # 3️⃣ Send
        sent = await send_meme(ctx, embed, embed_url, raw_url)

        # 4️⃣ Stats
        register_meme_message(
            sent.id,
            ctx.channel.id,
            ctx.guild.id,
            f"https://reddit.com{permalink}",
            post_dict["title"]
        )
        await update_stats(ctx.author.id, keyword or "", post_dict["subreddit"], nsfw=False)

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
                return await ctx.interaction.followup.send(
                    "✅ No memes found—try again later!", ephemeral=True
                )
            # fake a result object for footer
            result = type("F", (), {})()
            result.source_subreddit = rand_sub
            result.picked_via       = "random"

        # ─── BUILD EMBED ─────────────────────────────────────
        embed = Embed(
            title=post.title,
            url=f"https://reddit.com{post.permalink}"
        )
        embed.set_footer(
            text=f"r/{result.source_subreddit} • via {result.picked_via.upper()}"
        )

        raw_url   = get_image_url(post)
        embed_url = get_rxddit_url(raw_url)

        # only apologize if they asked for keyword but got no hits
        content = None
        if keyword and not got_keyword:
            content = (
                f"🔍 Sorry, I couldn’t find any memes containing `{keyword}`—"
                " here’s a random one instead!"
            )

        try:
            sent = await send_meme(ctx, url=raw_url, content=content)
            log.info("✅ send_meme succeeded message_id=%s", sent.id)
        except Exception:
            log.exception("Error in send_meme")
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
        )
        post = getattr(result, "post", None)

        # did we actually find something via keyword?
        got_keyword = bool(keyword and result.picked_via in ("cache", "live"))

        # ─── Final fallback: truly random ────────────────────
        if not post:
            all_subs = get_guild_subreddits(ctx.guild.id, "nsfw")
            rand_sub = random.choice(all_subs)
            post = await simple_random_meme(self.reddit, rand_sub)
            #if not post:
            #    return await ctx.interaction.followup.send(
            #        "✅ No NSFW memes right now—try again later!", ephemeral=True
            #    )
            result = type("F", (), {})()
            result.source_subreddit = rand_sub
            result.picked_via       = "random"

        # ─── BUILD EMBED ─────────────────────────────────────
        embed = Embed(
            title=post.title,
            url=f"https://reddit.com{post.permalink}"
        )
        embed.set_footer(
            text=f"r/{result.source_subreddit} • via {result.picked_via.upper()}"
        )

        raw_url   = get_image_url(post)
        embed_url = get_rxddit_url(raw_url)

        # only apologize if they asked for keyword but got no hits
        content = None
        if keyword and not got_keyword:
            content = (
                f"🔍 Sorry, I couldn’t find any NSFW memes containing `{keyword}`—"
                " here’s a random one instead!"
            )

        try:
            sent = await send_meme(ctx, url=raw_url, content=content)
            log.info("✅ NSFW send_meme succeeded message_id=%s", sent.id)
        except Exception:
            log.exception("Error in send_meme")
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
            )
            post = getattr(result, "post", None) if result else None

            # If nothing found, do a true random fallback from that subreddit
            if not post:
                log.info("No post found via keyword, trying random fallback in r/%s", subreddit)
                post = await simple_random_meme(self.reddit, subreddit)
                if not post:
                    log.info("No random meme found for r/%s, sending fail message.", subreddit)
                    return await ctx.followup.send(
                        f"✅ No memes found in r/{subreddit} right now—try again later!",
                        ephemeral=True
                    )
                # Build a result-like object for footer display
                result = type("F", (), {})()
                result.source_subreddit = subreddit
                result.picked_via       = "random"

            recent_ids = await get_recent_post_ids(ctx.channel.id, limit=20)
            if post and post.id in recent_ids:
                log.debug("🚫 recently sent, forcing fallback")
                post = None

            if not post:
                return await ctx.followup.send(
                    f"✅ No fresh posts in r/{subreddit} right now—try again later!",
                    ephemeral=True
                )

            raw_url = get_image_url(post)
            if raw_url.endswith(('.mp4', '.webm')):
                embed_url = get_rxddit_url(raw_url)  # use proxy for videos
            else:
                embed_url = raw_url  # original for images

            embed = Embed(
                title=post.title[:256],
                url=f"https://reddit.com{post.permalink}",
                description=f"r/{subreddit} • u/{post.author}"
            )

            content = None
            if getattr(result, "picked_via", None) == "random":
                content = "🔀 (random fallback)"

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
            await ctx.followup.send("❌ Error fetching meme from subreddit.", ephemeral=True)

    @commands.hybrid_command(name="validatesubreddits", description="Validate all current subreddits in the DB")
    @commands.has_permissions(administrator=True)
    async def validatesubreddits(self, ctx):
        await ctx.defer(ephemeral=True)
        results = {"sfw": [], "nsfw": []}
        for cat in ["sfw", "nsfw"]:
            subs = get_guild_subreddits(ctx.guild.id, cat)
            for sub in subs:
                try:
                    await self.reddit.subreddit(sub, fetch=True)
                    status = "✅"
                except:
                    status = "❌"
                results[cat].append((sub, status))
        lines = []
        for cat in ("sfw", "nsfw"):
            valids = sum(1 for _, st in results[cat] if st == "✅")
            total = len(results[cat])
            lines.append(f"**{cat.upper()}** ({valids}/{total} valid):")
            for name, status in results[cat]:
                lines.append(f"{status} {name}")
        await ctx.reply("\n".join(lines), ephemeral=True)

    @commands.hybrid_command(name="topreactions", description="Show top 5 memes by reactions")
    async def topreactions(self, ctx):
        log.info(f"[/topreactions] Command triggered by user {ctx.author} ({ctx.author.id})")
        try:
            results = await get_top_reacted_memes(5)
            log.debug(f"[/topreactions] Raw DB results: {results!r}")

            if not results:
                log.info("[/topreactions] No meme reactions recorded yet.")
                return await ctx.reply("No meme reactions recorded yet.", ephemeral=True)

            lines = []
            for msg_id, url, title, guild_id, channel_id, count in results:
                log.debug(f"[/topreactions] Message {msg_id}: {count} reactions - URL: {url}")
                msg_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{msg_id}"
                lines.append(
                    f"[Reddit Post]({url}) | [Discord]({msg_url}) — {title} ({count} reaction{'s' if count != 1 else ''})"
                )

            await ctx.reply("\n".join(lines), ephemeral=True)
            log.info(f"[/topreactions] Sent {len(lines)} leaderboard lines to user {ctx.author}.")

        except Exception as e:
            log.error(f"Error in /topreactions: {e}", exc_info=True)
            await ctx.reply("❌ Error loading top reactions leaderboard.", ephemeral=True)


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

            # Get top 3 users, subreddits, keywords
            top_users = sorted(users.items(), key=lambda x: x[1], reverse=True)[:3]
            top_subs = sorted(subs.items(), key=lambda x: x[1], reverse=True)[:3]
            top_kws = sorted(kws.items(), key=lambda x: x[1], reverse=True)[:3]

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

            await ctx.reply(embed=embed, ephemeral=True)

        except Exception:
            log.error("dashboard command error", exc_info=True)
            await ctx.reply("❌ Error generating dashboard.", ephemeral=True)

    @commands.hybrid_command(name="memestats", description="Show meme usage stats")
    async def memestats(self, ctx: commands.Context) -> None:
        try:
            all_stats = await get_dashboard_stats()
            total = all_stats.get('total_memes', 0)
            nsfw_count = all_stats.get('nsfw_memes', 0)
            kw_counts = all_stats.get('keyword_counts', {})
            top_kw = max(kw_counts, key=kw_counts.get) if kw_counts else 'N/A'
            log.debug("memestats: total=%d, nsfw=%d, top_kw=%s", total, nsfw_count, top_kw)
            await ctx.reply(
                f"Total Memes: {total} | NSFW: {nsfw_count} | Top Keyword: {top_kw}",
                ephemeral=True
            )
        except Exception:
            log.error("Error fetching meme stats", exc_info=True)
            await ctx.reply("❌ Error getting meme stats.", ephemeral=True)


    @commands.hybrid_command(name="topusers", description="Show top meme users")
    async def topusers(self, ctx):
        try:
            users = await get_top_users(5)
            leaderboard = []
            for uid, count in users:
                try:
                    member = await ctx.guild.fetch_member(int(uid))
                    name = member.display_name
                except Exception:
                    name = uid
                leaderboard.append(f"{name}: {count}")
            log.info("topusers: sending %d entries", len(leaderboard))
            await ctx.reply("\n".join(leaderboard) or "No data", ephemeral=True)
        except Exception:
            log.error("topusers command error", exc_info=True)
            await ctx.reply("❌ Error showing top users.", ephemeral=True)

    @commands.hybrid_command(name="topkeywords", description="Show top meme keywords")
    async def topkeywords(self, ctx):
        try:
            keywords = await get_top_keywords(5)
            leaderboard = [f"{kw}: {cnt}" for kw, cnt in keywords]
            log.info("topkeywords: sending %d items", len(leaderboard))
            await ctx.reply("\n".join(leaderboard) or "No data", ephemeral=True)
        except Exception:
            log.error("topkeywords command error", exc_info=True)
            await ctx.reply("❌ Error showing top keywords.", ephemeral=True)

    @commands.hybrid_command(name="topsubreddits", description="Show top used subreddits")
    async def topsubreddits(self, ctx):
        try:
            subs = await get_top_subreddits(5)
            leaderboard = [f"{sub}: {cnt}" for sub, cnt in subs]
            log.info("topsubreddits: sending %d items", len(leaderboard))
            await ctx.reply("\n".join(leaderboard) or "No data", ephemeral=True)
        except Exception:
            log.error("topsubreddits command error", exc_info=True)
            await ctx.reply("❌ Error showing top subreddits.", ephemeral=True)

    @commands.hybrid_command(name="listsubreddits", description="List current SFW and NSFW subreddits")
    async def listsubreddits(self, ctx):
        try:
            sfw = ", ".join(get_guild_subreddits(ctx.guild.id, 'sfw')) or "None"
            nsfw = ", ".join(get_guild_subreddits(ctx.guild.id, 'nsfw')) or "None"
            log.info("listsubreddits: %d sfw, %d nsfw", len(get_guild_subreddits(ctx.guild.id, 'sfw')), len(get_guild_subreddits(ctx.guild.id, 'nsfw')))
            embed = discord.Embed(title="Loaded Subreddits (per server)")
            embed.add_field(name="SFW", value=sfw, inline=False)
            embed.add_field(name="NSFW", value=nsfw, inline=False)
            await ctx.reply(embed=embed, ephemeral=True)
        except Exception:
            log.error("listsubreddits command error", exc_info=True)
            await ctx.reply("❌ Error listing subreddits.", ephemeral=True)

    @commands.hybrid_command(name="help", description="Show all available commands")
    async def help(self, ctx: commands.Context):
        """Show a list of available bot commands."""
        embed = discord.Embed(
            title="🤖 Bot Commands",
            description="Here's what I can do:",
            color=discord.Color.blurple()
        )

        # Economy
        embed.add_field(name="`/balance`", value="Check your coin balance", inline=False)
        embed.add_field(name="`/toprich`", value="Show top 5 richest users", inline=False)
        embed.add_field(name="`/buy <item>`", value="Purchase a shop item", inline=False)

        # Meme
        embed.add_field(name="`/meme [keyword]`", value="Fetch a SFW meme", inline=False)
        embed.add_field(name="`/nsfwmeme [keyword]`", value="Fetch a NSFW meme", inline=False)
        embed.add_field(name="`/r_ <subreddit> [keyword]`", value="Fetch from a specific subreddit", inline=False)
        embed.add_field(name="`/topreactions`", value="Show top 5 memes by reactions", inline=False)
        embed.add_field(name="`/memestats`", value="Show meme usage stats", inline=False)
        embed.add_field(name="`/topusers`", value="Show top meme users", inline=False)
        embed.add_field(name="`/topkeywords`", value="Show top meme keywords", inline=False)
        embed.add_field(name="`/topsubreddits`", value="Show top used subreddits", inline=False)
        embed.add_field(name="`/listsubreddits`", value="List current SFW & NSFW subreddits", inline=False)

        # Gamble (only help/list)
        embed.add_field(name="`/gamble help`", value="Show all available gambling games", inline=False)
        embed.add_field(name="`/gamble list`", value="List your recent bets and game stats", inline=False)

        # Voice / Audio
        embed.add_field(name="`/entrance`", value="Set or preview your entrance sound (full UI)", inline=False)
        embed.add_field(name="`/beep`", value="Play a random beep sound", inline=False)
        embed.add_field(name="`/beepfile <filename>`", value="Play a specific beep sound by filename", inline=False)
        embed.add_field(name="`/listbeeps`", value="List available beep sounds", inline=False)
        embed.add_field(name="`/cacheinfo`", value="Show the current audio cache stats", inline=False)

        await ctx.reply(embed=embed, ephemeral=True)

    @help.error
    async def help_error(self, ctx, error):
        log.error("Help command error", exc_info=error)
        await ctx.reply("❌ Could not show help. Please try again later.", ephemeral=True)


    @commands.hybrid_command(name="ping", description="Check bot latency")
    async def ping(self, ctx):
        """Check current latency of the bot."""
        latency_ms = round(self.bot.latency * 1000)
        await ctx.reply(f"🏓 Pong! Latency is {latency_ms}ms", ephemeral=True)

    @commands.hybrid_command(name="uptime", description="Show bot uptime")
    async def uptime(self, ctx):
        """Show how long the bot has been running."""
        try:
            elapsed = time.time() - self.start_time
            hours, rem = divmod(int(elapsed), 3600)
            minutes, seconds = divmod(rem, 60)
            await ctx.reply(f"⏱️ Uptime: {hours}h {minutes}m {seconds}s", ephemeral=True)
        except Exception:
            log.error("uptime command error", exc_info=True)
            await ctx.reply("❌ Error getting uptime.", ephemeral=True)

    @commands.hybrid_command(name="addsubreddit", description="Add a subreddit to SFW or NSFW list.")
    @commands.has_permissions(administrator=True)
    async def addsubreddit(self, ctx, name: str, category: str):
        """Add a subreddit (category must be 'sfw' or 'nsfw')."""
        if category not in ("sfw", "nsfw"):
            return await ctx.reply("Category must be 'sfw' or 'nsfw'.", ephemeral=True)
        add_guild_subreddit(ctx.guild.id, name, category)
        count = len(get_guild_subreddits(ctx.guild.id, category))
        warning = ""
        if count >= 40:
            warning = f"\n⚠️ **Warning:** {category.upper()} subreddits now has {count} entries. Too many may slow the bot or hit API limits!"
        await ctx.reply(f"✅ Added `{name}` to {category.upper()} subreddits for this server.{warning}", ephemeral=True)

    @commands.hybrid_command(name="removesubreddit", description="Remove a subreddit from SFW/NSFW lists.")
    @commands.has_permissions(administrator=True)
    async def removesubreddit(self, ctx, name: str, category: str):
        remove_guild_subreddit(ctx.guild.id, name, category)
        await ctx.reply(f"✅ Removed `{name}` from the {category.upper()} subreddits list for this server.", ephemeral=True)

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
    @commands.hybrid_command(name="cacheinfo", description="Show cache stats for meme system")
    @commands.has_permissions(administrator=True)
    async def cacheinfo(self, ctx):
        stats = await self.cache_service.get_cache_info()
        await ctx.reply(f"```\n{stats}\n```", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Meme(bot))
