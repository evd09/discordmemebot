# File: cogs/meme.py
import os
import random
import asyncio
import json
import time
import logging
import json
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque, defaultdict
from asyncprawcore import NotFound

import asyncpraw
import discord
from discord import Embed
from discord.ext import commands, tasks

from meme_stats import stats, update_stats, register_meme_message, meme_msgs, track_reaction

# Set up logger
log = logging.getLogger(__name__)

# Reaction tracking for /topreactions
reaction_counts = defaultdict(int)
meme_message_links = {}

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
        try:
            with open("subreddits.json", "r") as f:
                data = json.load(f)
            self.subreddits = {
                "sfw": data.get("sfw", []),
                "nsfw": data.get("nsfw", [])
            }
            log.info("Loaded subreddits.json successfully.")
        except Exception:
            log.error("Failed to load subreddits.json", exc_info=True)
            self.subreddits = {
                "sfw": [
                    "memes", "wholesomememes", "dankmemes", "funny",
                    "MemeEconomy", "me_irl", "comedyheaven", "AdviceAnimals"
                ],
                "nsfw": [
                    "nsfwmemes", "dirtymemes", "pornmemes", "memesgonewild",
                    "rule34memes", "lewdanime", "EcchiMemes", "sexmemes"
                ]
            }
        self.cache: Dict[str, List[Dict[str, float]]] = {}
        # Start the background prune task
        self._prune_cache.start()
        self.bot.loop.create_task(self.validate_subreddits())

    def cog_unload(self) -> None:
        self._prune_cache.cancel()

    @tasks.loop(seconds=60)
    async def _prune_cache(self):
        """Periodically prune the in-memory cache of seen posts."""
        now = asyncio.get_event_loop().time()
        for key, entries in list(self.cache.items()):
            self.cache[key] = [
                e for e in entries
                if now - e.get("time", 0) < CACHE_DURATION
            ]

    def reload_subreddits_from_file(self):
        try:
            with open("subreddits.json", "r") as f:
                data = json.load(f)
            self.subreddits = {
                "sfw": data.get("sfw", []),
                "nsfw": data.get("nsfw", [])
            }
            log.info("Reloaded subreddits.json successfully.")
            return True
        except Exception as e:
            log.error("Failed to reload subreddits.json", exc_info=True)
            return False

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
        for cat, subs in list(self.subreddits.items()):
            for sub in subs:
                t0 = time.time()
                try:
                    await self._throttle_api()
                    await self.reddit.subreddit(sub, fetch=True)
                    status = "✅"
                except:
                    status = "❌"
                report[cat].append((sub, status, time.time() - t0))
        self.subreddits = {cat: [s for s, st, _ in report[cat] if st == "✅"] for cat in report}
        total = time.time() - start
        log.info("Subreddit validation complete in %.2fs", total)
        return report, total

    async def fetch_meme(self, category: str, keyword: Optional[str] = None, notify_wait=None):
        subs = self.subreddits.get(category, [])
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
        if str(msg.id) in meme_msgs:
            await track_reaction(msg.id, user.id, str(reaction.emoji))
            log.debug("Tracked reaction %s on message %s by user %s", reaction.emoji, msg.id, user.id)

    @commands.hybrid_command(name="meme", description="Fetch a SFW meme")
    async def meme(self, ctx, keyword: Optional[str] = None):
        """Fetch a SFW meme, with optional keyword filter, fallback notice, and rewards."""
        ctx._chosen_fallback = False
        ctx._no_reward       = False

        async def notify_wait(wait_seconds):
            await ctx.interaction.followup.send(
                f"⚠️ Bot is rate-limited by Reddit API. Waiting {wait_seconds:.1f}s…",
                ephemeral=True
            )

        # defer so we can use followup.send()
        await ctx.defer()

        try:
            chosen, fallback = await self.fetch_meme('sfw', keyword, notify_wait=notify_wait)
            if not chosen:
                ctx._no_reward = True
                return await ctx.interaction.followup.send(
                    "😔 Couldn't find any memes.",
                    ephemeral=True
                )

            # keyword-only fallback: notify, but still send the embed
            if keyword and fallback:
                # only suppress the keyword bonus, not the base reward
                ctx._chosen_fallback = True
                await ctx.interaction.followup.send(
                    f"❌ Couldn't find any memes for `{keyword}`, here's a random one!",
                    ephemeral=True
                )

            # build & send embed
            media_url = self.get_media_url(chosen)
            embed = Embed(title=chosen.title, url=f"https://reddit.com{chosen.permalink}")
            if media_url and (media_url.lower().endswith(('.mp4', '.webm', '.gif')) or "v.redd.it" in media_url):
                thumb = self.get_video_thumbnail(chosen)
                if thumb:
                    embed.set_image(url=thumb)
                embed.add_field(name="Video Link", value=media_url, inline=False)
            else:
                embed.set_image(url=media_url)
            embed.set_footer(text=f"r/{chosen.subreddit.display_name}")

            await ctx.interaction.followup.send(embed=embed)

            # register + stats
            await register_meme_message(
                ctx.interaction.id, ctx.channel.id, ctx.guild.id,
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

    @commands.hybrid_command(name="nsfwmeme", description="Fetch a NSFW meme (NSFW channels only)")
    async def nsfwmeme(self, ctx, keyword: Optional[str] = None):
        """Fetch a NSFW meme, with optional keyword filter, fallback notice, and rewards."""
        ctx._chosen_fallback = False
        ctx._no_reward       = False

        # 1) early-exit if not NSFW channel
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

        # defer so we can use followup.send()
        await ctx.defer()

        try:
            chosen, fallback = await self.fetch_meme('nsfw', keyword, notify_wait=notify_wait)
            if not chosen:
                ctx._no_reward = True
                return await ctx.interaction.followup.send(
                    "😔 Couldn't find any NSFW memes.",
                    ephemeral=True
                )

            # keyword-only fallback: notify, but still send the embed
            if keyword and fallback:
                # only suppress the keyword bonus, not the base reward
                ctx._chosen_fallback = True
                await ctx.interaction.followup.send(
                    f"❌ Couldn't find any NSFW memes for `{keyword}`, here's a random one!",
                    ephemeral=True
                )

            # build & send embed
            media_url = self.get_media_url(chosen)
            embed = Embed(title=chosen.title, url=f"https://reddit.com{chosen.permalink}")
            if media_url and (media_url.lower().endswith(('.mp4', '.webm', '.gif')) or "v.redd.it" in media_url):
                thumb = self.get_video_thumbnail(chosen)
                if thumb:
                    embed.set_image(url=thumb)
                embed.add_field(name="Video Link", value=media_url, inline=False)
            else:
                embed.set_image(url=media_url)
            embed.set_footer(text=f"r/{chosen.subreddit.display_name}")

            await ctx.interaction.followup.send(embed=embed)

            # register + stats
            await register_meme_message(
                ctx.interaction.id, ctx.channel.id, ctx.guild.id,
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
        """Fetch a meme from a given subreddit, with optional keyword filtering and fallback."""
        async def notify_wait(wait_seconds):
            await ctx.send(
                f"⚠️ Bot is rate-limited by Reddit API. Waiting for {wait_seconds:.1f}s before continuing...",
                ephemeral=True
            )

        try:
            await ctx.defer()

            # Validate subreddit
            try:
                sub = await self.reddit.subreddit(subreddit, fetch=True)
            except NotFound:
                return await ctx.reply(f"❌ Could not find subreddit `{subreddit}`.", ephemeral=True)

            # Throttle if needed
            await self._throttle_api(notify_wait=notify_wait)

            # Pull posts
            posts = [
                p async for p in sub.hot(limit=50)
                if not p.stickied and self.get_media_url(p)
            ]
            if not posts:
                return await ctx.reply("😔 No media posts found.", ephemeral=True)

            # Keyword filter
            fallback = False
            if keyword:
                kw = keyword.lower()
                filtered = [p for p in posts if kw in (p.title or "").lower() or kw in (p.url or "").lower()]
                if filtered:
                    posts = filtered
                else:
                    fallback = True

            # Choose one
            chosen = random.choice(posts)
            media_url = self.get_media_url(chosen)

            if fallback:
                await ctx.send(f"❌ Couldn't find any posts for `{keyword}`, here's a random one!")

            # Build embed
            embed = Embed(
                title=chosen.title,
                url=f"https://reddit.com{chosen.permalink}"
            )
            if media_url and (
                media_url.lower().endswith((".mp4", ".webm", ".gif")) or "v.redd.it" in media_url
            ):
                thumb = self.get_video_thumbnail(chosen)
                if thumb:
                    embed.set_image(url=thumb)
                embed.add_field(name="Video Link", value=media_url, inline=False)
            else:
                embed.set_image(url=media_url)

            embed.set_footer(text=f"r/{chosen.subreddit.display_name}")

            # Send + register
            msg = await ctx.send(embed=embed)
            await register_meme_message(
                msg.id,
                ctx.channel.id,
                ctx.guild.id,
                f"https://reddit.com{chosen.permalink}",
                chosen.title
            )
            update_stats(
                ctx.author.id,
                keyword or "",
                chosen.subreddit.display_name,
                nsfw=False
            )

        except Exception:
            log.error("r_ command error", exc_info=True)
            await ctx.reply(
                "❌ Oops! We ran into an issue fetching from that subreddit. Please let the admin know so they can take a look.",
                ephemeral=True
            )

    @commands.hybrid_command(name="reloadsubreddits", description="Reload and validate subreddit lists")
    async def reloadsubreddits(self, ctx: commands.Context):
        await ctx.defer(ephemeral=True)
        # 1. Read from disk
        try:
            with open("subreddits.json", "r") as f:
                data = json.load(f)
            self.subreddits = {
                "sfw": data.get("sfw", []),
                "nsfw": data.get("nsfw", [])
            }
            log.info("Reloaded subreddits.json from disk")
        except Exception:
            log.error("Failed to reload subreddits.json from disk", exc_info=True)
            return await ctx.send(
                "❌ Failed to reload subreddits.json from disk. Please check logs.",
                ephemeral=True
            )
        try:
            report, total = await self.validate_subreddits()
            lines: List[str] = []
            for cat in ('sfw', 'nsfw'):
                total_checked = len(report[cat])
                total_valid = sum(1 for _, status, _ in report[cat] if status == "✅")
                lines.append(f"**{cat.upper()}** ({total_valid}/{total_checked} valid):")
                for name, status, dt in report[cat]:
                    lines.append(f"{status} {name:15} — {dt:.2f}s")
            lines.append(f"**Total validation time:** {total:.2f}s")
            await ctx.send("\n".join(lines), ephemeral=True)

            sfw_valid = sum(1 for _, status, _ in report['sfw'] if status == "✅")
            nsfw_valid = sum(1 for _, status, _ in report['nsfw'] if status == "✅")
            await ctx.send(
                f"✅ Subreddit lists reloaded and tested! "
                f"({sfw_valid}/{len(report['sfw'])} SFW, {nsfw_valid}/{len(report['nsfw'])} NSFW)",
                ephemeral=True
            )
        except Exception:
            log.error("Error during subreddit validation", exc_info=True)
            await ctx.send(
                "❌ There was an error validating subreddit lists. Please check logs.",
                ephemeral=True
            )

    @commands.hybrid_command(name="topreactions", description="Show top 5 memes by reactions")
    async def topreactions(self, ctx):
        if not meme_msgs:
            return await ctx.reply("No memes have been posted yet!", ephemeral=True)

        top = sorted(
            meme_msgs.items(),
            key=lambda x: sum(x[1].get("reactions", {}).values()),
            reverse=True
        )[:5]

        if not top or all(sum(x[1].get("reactions", {}).values()) == 0 for x in top):
            return await ctx.reply("No meme reactions recorded yet.", ephemeral=True)

        lines = []
        for msg_id, meta in top:
            count = sum(meta.get("reactions", {}).values())
            url = meta.get("url")
            title = meta.get("title")
            guild_id = meta.get("guild_id")
            channel_id = meta.get("channel_id")
            msg_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{msg_id}"
            lines.append(f"[Reddit Post]({url}) | [Discord]({msg_url}) — {title} ({count} reaction{'s' if count != 1 else ''})")

        log.info("Displaying top %d reactions", len(lines))
        await ctx.reply("\n".join(lines), ephemeral=True)

    @commands.hybrid_command(name="dashboard", description="Show a stats dashboard")
    async def dashboard(self, ctx):
        """Display total memes, top users, subreddits, and keywords."""
        try:
            # 1) Read from stats.json
            with open("stats.json", "r") as f:
                all_stats = json.load(f)

            total = all_stats.get("total_memes", 0)
            nsfw  = all_stats.get("nsfw_memes", 0)

            # 2) Top 3 users (resolve IDs to names)
            users = all_stats.get("user_counts", {})
            top_users = sorted(users.items(), key=lambda x: x[1], reverse=True)[:3]
            user_lines = []
            for uid, count in top_users:
                try:
                    member = ctx.guild.get_member(int(uid)) or await ctx.guild.fetch_member(int(uid))
                    name = member.display_name
                except Exception:
                    name = f"<@{uid}>"
                user_lines.append(f"{name}: {count}")
            user_lines = "\n".join(user_lines) or "None"

            # 3) Top 3 subreddits
            subs = all_stats.get("subreddit_counts", {})
            top_subs = sorted(subs.items(), key=lambda x: x[1], reverse=True)[:3]
            sub_lines = "\n".join(f"{s}: {c}" for s, c in top_subs) or "None"

            # 4) Top 3 keywords
            kws = all_stats.get("keyword_counts", {})
            top_kws = sorted(kws.items(), key=lambda x: x[1], reverse=True)[:3]
            kw_lines = "\n".join(f"{k}: {c}" for k, c in top_kws) or "None"

            # 5) Build the embed
            embed = discord.Embed(
                title="📊 MemeBot Dashboard",
                color=discord.Color.blurple(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="😂 Total Memes",    value=str(total),      inline=True)
            embed.add_field(name="🔞 NSFW Memes",     value=str(nsfw),       inline=True)
            embed.add_field(name="\u200b",         value="\u200b",        inline=True)  # spacer
            embed.add_field(name="🥇 Top Users",    value=user_lines,      inline=False)
            embed.add_field(name="🌐 Top Subreddits", value=sub_lines,    inline=False)
            embed.add_field(name="🔍 Top Keywords",  value=kw_lines,      inline=False)

            await ctx.reply(embed=embed, ephemeral=True)

        except Exception:
            log.error("dashboard command error", exc_info=True)
            await ctx.reply("❌ Error generating dashboard.", ephemeral=True)

    @commands.hybrid_command(name="memestats", description="Show meme usage stats")
    async def memestats(self, ctx: commands.Context) -> None:
        try:
            total = stats.get('total_memes', 0)
            nsfw_count = stats.get('nsfw_memes', 0)
            kw_counts = stats.get('keyword_counts', {})
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
            users = stats.get('user_counts', {})
            leaderboard = []
            for uid, count in sorted(users.items(), key=lambda x: x[1], reverse=True)[:5]:
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
            kw_counts = stats.get('keyword_counts', {})
            leaderboard = [f"{kw}: {cnt}" for kw, cnt in sorted(kw_counts.items(), key=lambda x: x[1], reverse=True)[:5]]
            log.info("topkeywords: sending %d items", len(leaderboard))
            await ctx.reply("\n".join(leaderboard) or "No data", ephemeral=True)
        except Exception:
            log.error("topkeywords command error", exc_info=True)
            await ctx.reply("❌ Error showing top keywords.", ephemeral=True)

    @commands.hybrid_command(name="topsubreddits", description="Show top used subreddits")
    async def topsubreddits(self, ctx):
        try:
            sub_counts = stats.get('subreddit_counts', {})
            leaderboard = [f"{sub}: {cnt}" for sub, cnt in sorted(sub_counts.items(), key=lambda x: x[1], reverse=True)[:5]]
            log.info("topsubreddits: sending %d items", len(leaderboard))
            await ctx.reply("\n".join(leaderboard) or "No data", ephemeral=True)
        except Exception:
            log.error("topsubreddits command error", exc_info=True)
            await ctx.reply("❌ Error showing top subreddits.", ephemeral=True)

    @commands.hybrid_command(name="listsubreddits", description="List current SFW and NSFW subreddits")
    async def listsubreddits(self, ctx):
        try:
            sfw = ", ".join(self.subreddits.get('sfw', [])) or "None"
            nsfw = ", ".join(self.subreddits.get('nsfw', [])) or "None"
            log.info("listsubreddits: %d sfw, %d nsfw", len(self.subreddits.get('sfw', [])), len(self.subreddits.get('nsfw', [])))
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
        embed.add_field(name="`/reloadsubreddits`", value="Reload & validate subreddit lists", inline=False)
        embed.add_field(name="`/topreactions`", value="Show top 5 memes by reactions", inline=False)
        embed.add_field(name="`/memestats`", value="Show meme usage stats", inline=False)
        embed.add_field(name="`/topusers`", value="Show top meme users", inline=False)
        embed.add_field(name="`/topkeywords`", value="Show top meme keywords", inline=False)
        embed.add_field(name="`/topsubreddits`", value="Show top used subreddits", inline=False)
        embed.add_field(name="`/listsubreddits`", value="List current SFW & NSFW subreddits", inline=False)

        # Gamble
        embed.add_field(name="`/gamble flip <amount>`", value="Interactive coin flip", inline=False)
        embed.add_field(name="`/gamble roll <amount>`", value="Interactive dice roll", inline=False)
        embed.add_field(name="`/gamble highlow <amount>`", value="Interactive high-low card", inline=False)
        embed.add_field(name="`/gamble slots <amount>`", value="Spin the slots", inline=False)
        embed.add_field(name="`/gamble crash <amount>`", value="Crash game — cash out before it blows", inline=False)
        embed.add_field(name="`/gamble blackjack <amount>`", value="Interactive blackjack", inline=False)
        embed.add_field(name="`/gamble lottery`", value="Enter today's 10-coin lottery", inline=False)

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

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Meme(bot))

