# File: cogs/meme.py
import os
import random
import asyncio
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque
from asyncprawcore import NotFound
from meme_stats import add_subreddit, remove_subreddit, get_subreddits
import asyncpraw
import discord
from discord import Embed
from discord.ext import commands, tasks
from urllib.parse import urlparse, parse_qs, unquote

from meme_stats import (
    update_stats,
    register_meme_message,
    track_reaction,
    get_dashboard_stats,
    get_top_users,
    get_top_keywords,
    get_top_subreddits,
    get_reactions_for_message,
    get_top_reacted_memes,
)

# Set up logger
log = logging.getLogger(__name__)

# How long to remember which memes we've sent
CACHE_DURATION = 300
# Valid media extensions
MEDIA_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.mp4', '.webm')

class Meme(commands.Cog):
    """
    Cog for fetching memes, validating subreddit lists, and providing meme-related commands.
    """
    def __init__(self, bot: commands.Bot):
        self.start_time = time.time()
        self.recent_ids = deque(maxlen=200)
        self._api_lock = asyncio.Lock()
        self.api_calls = 0
        self.api_reset_time = time.time() + 60
        self.bot = bot

        log.info(
            "MemeBot cog initialized at %s",
            time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.start_time))
        )

        self.reddit = asyncpraw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent="MemeBot (by u/YourUsername)"
        )

        self.cache: Dict[str, List[Dict[str, float]]] = {}

        # Start the background prune task
    def cog_unload(self) -> None:
        self._prune_cache.cancel()

    @tasks.loop(seconds=60)
    async def _prune_cache(self) -> None:
        now = asyncio.get_event_loop().time()
        for key, entries in list(self.cache.items()):
            self.cache[key] = [e for e in entries if now - e["time"] < CACHE_DURATION]

    async def _throttle_api(self, notify_wait=None, max_retries=3) -> None:
        retries = 0
        while True:
            try:
                async with self._api_lock:
                    now = time.time()
                    if now > self.api_reset_time:
                        self.api_calls = 0
                        self.api_reset_time = now + 60

                    if self.api_calls >= 50:
                        wait = self.api_reset_time - now
                        log.info("API rate limit reached, sleeping for %.2f seconds", wait)
                        if notify_wait:
                            await notify_wait(wait)
                        await asyncio.sleep(wait)
                        self.api_calls = 0
                        self.api_reset_time = time.time() + 60

                    self.api_calls += 1
                    self._last_api_call = time.time()
                break
            except Exception as e:
                retries += 1
                log.warning("API call failed (retry %d/%d): %s", retries, max_retries, e)
                if retries >= max_retries:
                    log.error("Max API retries reached", exc_info=True)
                    raise
                backoff = 2 ** retries
                log.info("Backing off for %d seconds before retrying", backoff)
                await asyncio.sleep(backoff)

    def get_media_url(self, submission) -> Optional[str]:
        if getattr(submission, 'is_gallery', False):
            media_id = submission.gallery_data['items'][0]['media_id']
            meta = submission.media_metadata.get(media_id, {})
            url = meta.get('s', {}).get('u', '')
            return url.replace('&amp;', '&') if url else None
        if getattr(submission, 'is_video', False):
            rv = submission.media.get('reddit_video', {})
            return rv.get('fallback_url')
        preview = getattr(submission, 'preview', None)
        if preview and getattr(preview, 'images', None):
            img = preview.images[0].get('source', {})
            url = img.get('url', '')
            return url.replace('&amp;', '&') if url else None
        if preview:
            rvp = getattr(preview, 'reddit_video_preview', None)
            if rvp and getattr(rvp, 'fallback_url', None):
                return rvp.fallback_url
        url = submission.url
        if url.endswith('.gifv'):
            return url[:-5] + '.mp4'
        if any(url.lower().endswith(ext) for ext in MEDIA_EXTENSIONS):
            return url
        return None

    def get_video_thumbnail(self, submission) -> Optional[str]:
        preview = getattr(submission, 'preview', None)
        if preview and getattr(preview, 'images', None):
            img = preview.images[0].get('source', {})
            url = img.get('url', '')
            return url.replace('&amp;', '&') if url else None
        thumbnail = getattr(submission, 'thumbnail', None)
        if thumbnail and thumbnail.startswith('http'):
            return thumbnail
        return None
    
    async def validate_subreddits(self):
        start = time.time()
        report: Dict[str, List[tuple]] = {"sfw": [], "nsfw": []}
        for cat in ["sfw", "nsfw"]:
            subs = get_subreddits(cat)
            for sub in subs:
                t0 = time.time()
                try:
                    await self._throttle_api()
                    await self.reddit.subreddit(sub, fetch=True)
                    status = "✅"
                except:
                    status = "❌"
                report[cat].append((sub, status, time.time() - t0))
        total = time.time() - start
        log.info("Subreddit validation complete in %.2fs", total)
        return report, total

    async def fetch_meme(self, category: str, keyword: Optional[str] = None, notify_wait=None):
        subs = get_subreddits(category)
        log.debug("fetch_meme: category=%s, keyword=%s, subs=%s", category, keyword, subs)
        if not subs:
            log.warning("No subreddits available for category '%s'", category)
            return None, False

        sub_name = random.choice(subs)
        try:
            await self._throttle_api(notify_wait=notify_wait)
            subreddit = await self.reddit.subreddit(sub_name, fetch=True)
            log.debug("Picked subreddit: %s", sub_name)
        except Exception:
            log.error("Could not fetch subreddit '%s'", sub_name, exc_info=True)
            return None, False

        await self._throttle_api(notify_wait=notify_wait)
        posts = [p async for p in subreddit.hot(limit=50) if not p.stickied]
        log.debug("Pulled %d hot posts from r/%s", len(posts), sub_name)

        posts = [p for p in posts if self.get_media_url(p)]
        log.debug("%d posts have valid media", len(posts))

        fallback = False
        if keyword:
            kw = keyword.lower()
            filtered = [p for p in posts if kw in (p.title or '').lower() or kw in (p.url or '').lower()]
            log.debug("%d posts after keyword filter for '%s'", len(filtered), keyword)
            if filtered:
                posts = filtered
            else:
                fallback = True
        if not posts:
            log.info("No posts left after filtering for '%s'", keyword)
            return None, False

        fresh = [p for p in posts if p.id not in self.recent_ids]
        log.debug("%d fresh posts (not recently seen)", len(fresh))
        chosen = random.choice(fresh if fresh else posts)
        self.recent_ids.append(chosen.id)

        log.info("Chosen post: %s (id=%s)", chosen.title, chosen.id)
        return chosen, fallback

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        msg = reaction.message
        await track_reaction(msg.id, user.id, str(reaction.emoji))
        log.debug("Tracked reaction %s on message %s by user %s", reaction.emoji, msg.id, user.id)

    @commands.hybrid_command(name="meme", description="Fetch a SFW meme")
    async def meme(self, ctx, keyword: Optional[str] = None):
        """
        Fetch a SFW meme, with optional keyword filter, fallback notice, and rewards.
        - Images: embedded in the message
        - Videos/GIFs: Discord inlines the video/gif if sent as content
        - v.redd.it videos: Discord can't inline, so send a clickable link
        """
        ctx._chosen_fallback = False
        ctx._no_reward = False

        async def notify_wait(wait_seconds):
            await ctx.interaction.followup.send(
                f"⚠️ Bot is rate-limited by Reddit API. Waiting {wait_seconds:.1f}s…",
                ephemeral=True
            )

        await ctx.defer()
        try:
            chosen, fallback = await self.fetch_meme('sfw', keyword, notify_wait=notify_wait)
            if not chosen:
                ctx._no_reward = True
                return await ctx.interaction.followup.send(
                    "😔 Couldn't find any memes.", ephemeral=True
                )

            media_url = self.get_media_url(chosen)
            media_url = self.resolve_reddit_media_url(media_url)

            embed = Embed(title=chosen.title, url=f"https://reddit.com{chosen.permalink}")
            if keyword and fallback:
                ctx._chosen_fallback = True
                embed.description = f"❌ Couldn't find any memes for `{keyword}`, here's a random one!"
            embed.set_footer(text=f"r/{chosen.subreddit.display_name}")

            content = None
            # Show v.redd.it warning first for clarity
            if media_url and "v.redd.it" in media_url:
                content = f"⚠️ Discord can't play this video inline. [Click here to view the video on Reddit]({media_url})"
                thumb = self.get_video_thumbnail(chosen)
                if thumb:
                    embed.set_image(url=thumb)
            elif media_url and media_url.lower().endswith(('.mp4', '.webm', '.gif')):
                content = media_url
                thumb = self.get_video_thumbnail(chosen)
                if thumb:
                    embed.set_image(url=thumb)
            elif media_url and media_url.lower().endswith(('.jpg', '.jpeg', '.png')):
                embed.set_image(url=media_url)

            sent_msg = await ctx.interaction.followup.send(content=content, embed=embed, wait=True)

            await register_meme_message(
                sent_msg.id, ctx.channel.id, ctx.guild.id,
                f"https://reddit.com{chosen.permalink}", chosen.title
            )
            update_stats(ctx.author.id, keyword or '', chosen.subreddit.display_name, nsfw=False)

        except Exception:
            ctx._no_reward = True
            log.error("meme command error", exc_info=True)
            await ctx.interaction.followup.send(
                "❌ Oops! Something went wrong fetching memes. Please let the admin know.",
                ephemeral=True
            )

    # Make sure resolve_reddit_media_url is a static method in your class:
    @staticmethod
    def resolve_reddit_media_url(url: str) -> str:
        log.debug(f"resolve_reddit_media_url called with: {url}")
        if url and url.startswith("https://www.reddit.com/media?"):
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            real_url = qs.get('url', [None])[0]
            if real_url:
                log.debug(f"Resolved real media url: {real_url}")
                return unquote(real_url)
        return url

    @commands.hybrid_command(name="nsfwmeme", description="Fetch a NSFW meme (NSFW channels only)")
    async def nsfwmeme(self, ctx, keyword: Optional[str] = None):
        ctx._chosen_fallback = False
        ctx._no_reward = False

        if not ctx.channel.is_nsfw():
            ctx._no_reward = True
            return await ctx.interaction.response.send_message(
                "🔞 You can only use NSFW memes in NSFW channels.",
                ephemeral=True
            )

        async def notify_wait(wait_seconds):
            await ctx.interaction.followup.send(
                f"⚠️ Bot is rate-limited by Reddit API. Waiting {wait_seconds:.1f}s…",
                ephemeral=True
            )

        await ctx.defer()
        try:
            chosen, fallback = await self.fetch_meme('nsfw', keyword, notify_wait=notify_wait)
            if not chosen:
                ctx._no_reward = True
                return await ctx.interaction.followup.send(
                    "😔 Couldn't find any NSFW memes.", ephemeral=True
                )

            media_url = self.get_media_url(chosen)
            media_url = self.resolve_reddit_media_url(media_url)

            embed = Embed(title=chosen.title, url=f"https://reddit.com{chosen.permalink}")
            if keyword and fallback:
                ctx._chosen_fallback = True
                embed.description = f"❌ Couldn't find any memes for `{keyword}`, here's a random one!"
            embed.set_footer(text=f"r/{chosen.subreddit.display_name}")

            content = None
            if media_url and media_url.lower().endswith(('.mp4', '.webm', '.gif')):
                content = media_url
                thumb = self.get_video_thumbnail(chosen)
                if thumb:
                    embed.set_image(url=thumb)
            elif media_url and "v.redd.it" in media_url:
                content = f"⚠️ Discord can't play this video inline. [Click here to view the video on Reddit]({media_url})"
                thumb = self.get_video_thumbnail(chosen)
                if thumb:
                    embed.set_image(url=thumb)
            elif media_url and media_url.lower().endswith((".jpg", ".jpeg", ".png")):
                embed.set_image(url=media_url)

            sent_msg = await ctx.interaction.followup.send(content=content, embed=embed, wait=True)

            await register_meme_message(
                sent_msg.id, ctx.channel.id, ctx.guild.id,
                f"https://reddit.com{chosen.permalink}", chosen.title
            )
            update_stats(ctx.author.id, keyword or '', chosen.subreddit.display_name, nsfw=True)

        except Exception:
            ctx._no_reward = True
            log.error("nsfwmeme command error", exc_info=True)
            await ctx.interaction.followup.send(
                "❌ Oops! Something went wrong fetching NSFW memes. Please let the admin know.",
                ephemeral=True
            )

    @commands.hybrid_command(name="r_", description="Fetch a meme from a specific subreddit")
    async def r_(self, ctx, subreddit: str, keyword: Optional[str] = None):
        async def notify_wait(wait_seconds):
            await ctx.send(
                f"⚠️ Bot is rate-limited by Reddit API. Waiting for {wait_seconds:.1f}s before continuing...",
                ephemeral=True
            )

        await ctx.defer()
        try:
            try:
                sub = await self.reddit.subreddit(subreddit, fetch=True)
            except NotFound:
                return await ctx.reply(f"❌ Could not find subreddit `{subreddit}`.", ephemeral=True)

            await self._throttle_api(notify_wait=notify_wait)
            posts = [
                p async for p in sub.hot(limit=50)
                if not p.stickied and self.get_media_url(p)
            ]
            if not posts:
                return await ctx.reply("😔 No media posts found.", ephemeral=True)

            fallback = False
            if keyword:
                kw = keyword.lower()
                filtered = [p for p in posts if kw in (p.title or "").lower() or kw in (p.url or "").lower()]
                if filtered:
                    posts = filtered
                else:
                    fallback = True

            chosen = random.choice(posts)
            media_url = self.get_media_url(chosen)
            media_url = self.resolve_reddit_media_url(media_url)

            embed = Embed(title=chosen.title, url=f"https://reddit.com{chosen.permalink}")
            if keyword and fallback:
                embed.description = f"❌ Couldn't find any posts for `{keyword}`, here's a random one!"
            embed.set_footer(text=f"r/{chosen.subreddit.display_name}")

            content = None
            if media_url and media_url.lower().endswith(('.mp4', '.webm', '.gif')):
                content = media_url
                thumb = self.get_video_thumbnail(chosen)
                if thumb:
                    embed.set_image(url=thumb)
            elif media_url and "v.redd.it" in media_url:
                content = f"⚠️ Discord can't play this video inline. [Click here to view the video on Reddit]({media_url})"
                thumb = self.get_video_thumbnail(chosen)
                if thumb:
                    embed.set_image(url=thumb)
            elif media_url and media_url.lower().endswith((".jpg", ".jpeg", ".png")):
                embed.set_image(url=media_url)

            sent_msg = await ctx.interaction.followup.send(content=content, embed=embed, wait=True)

            await register_meme_message(
                sent_msg.id, ctx.channel.id, ctx.guild.id,
                f"https://reddit.com{chosen.permalink}", chosen.title
            )
            update_stats(ctx.author.id, keyword or '', chosen.subreddit.display_name, nsfw=False)

        except Exception:
            log.error("r_ command error", exc_info=True)
            await ctx.reply(
                "❌ Oops! We ran into an issue fetching from that subreddit. Please let the admin know so they can take a look.",
                ephemeral=True
            )

    @commands.hybrid_command(name="validatesubreddits", description="Validate all current subreddits in the DB")
    @commands.has_permissions(administrator=True)
    async def validatesubreddits(self, ctx):
        await ctx.defer(ephemeral=True)
        results = {"sfw": [], "nsfw": []}
        for cat in ["sfw", "nsfw"]:
            subs = get_subreddits(cat)
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
            results = get_top_reacted_memes(5)
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
            all_stats = get_dashboard_stats()
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
            all_stats = get_dashboard_stats()
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
            users = get_top_users(5)
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
            keywords = get_top_keywords(5)
            leaderboard = [f"{kw}: {cnt}" for kw, cnt in keywords]
            log.info("topkeywords: sending %d items", len(leaderboard))
            await ctx.reply("\n".join(leaderboard) or "No data", ephemeral=True)
        except Exception:
            log.error("topkeywords command error", exc_info=True)
            await ctx.reply("❌ Error showing top keywords.", ephemeral=True)

    @commands.hybrid_command(name="topsubreddits", description="Show top used subreddits")
    async def topsubreddits(self, ctx):
        try:
            subs = get_top_subreddits(5)
            leaderboard = [f"{sub}: {cnt}" for sub, cnt in subs]
            log.info("topsubreddits: sending %d items", len(leaderboard))
            await ctx.reply("\n".join(leaderboard) or "No data", ephemeral=True)
        except Exception:
            log.error("topsubreddits command error", exc_info=True)
            await ctx.reply("❌ Error showing top subreddits.", ephemeral=True)

    @commands.hybrid_command(name="listsubreddits", description="List current SFW and NSFW subreddits")
    async def listsubreddits(self, ctx):
        try:
            sfw = ", ".join(get_subreddits('sfw')) or "None"
            nsfw = ", ".join(get_subreddits('nsfw')) or "None"
            log.info("listsubreddits: %d sfw, %d nsfw", len(get_subreddits('sfw')), len(get_subreddits('nsfw')))
            embed = discord.Embed(title="Loaded Subreddits")
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
        add_subreddit(name, category)
        count = len(get_subreddits(category))
        warning = ""
        if count >= 40:
            warning = f"\n⚠️ **Warning:** {category.upper()} subreddits now has {count} entries. Too many may slow the bot or hit API limits!"
        await ctx.reply(f"✅ Added `{name}` to {category.upper()} subreddits.{warning}", ephemeral=True)

    @commands.hybrid_command(name="removesubreddit", description="Remove a subreddit from SFW/NSFW lists.")
    @commands.has_permissions(administrator=True)
    async def removesubreddit(self, ctx, name: str):
        remove_subreddit(name)
        await ctx.reply(f"✅ Removed `{name}` from the subreddits list.", ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Meme(bot))
