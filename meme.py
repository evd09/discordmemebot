# File: cogs/meme.py
import os
import random
import asyncio
import json
import time
from typing import Dict, List, Optional
from collections import deque, defaultdict

import asyncpraw
import discord
from discord import Embed
from discord.ext import commands, tasks

from meme_stats import stats, update_stats, register_meme_message, meme_msgs, track_reaction

# Reaction tracking for /topreactions
reaction_counts = defaultdict(int)         # {msg_id: reaction_count}
meme_message_links = dict()                # {msg_id: (guild_id, channel_id, message_id, reddit_url)}

# How long to remember which memes we've sent (in seconds)
CACHE_DURATION = 300
# Valid media extensions for embedding
MEDIA_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.mp4', '.webm')

class Meme(commands.Cog):
    """
    Cog for fetching memes, validating subreddit lists, and providing meme-related commands.
    """
    def __init__(self, bot: commands.Bot):
        self.recent_ids = deque(maxlen=200)
        self._last_api_call = time.time()
        self._min_interval = 1/50
        self._api_lock = asyncio.Lock()
        self.api_calls = 0
        self.api_reset_time = time.time() + 60

        self.bot = bot
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
        except Exception:
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
        self._prune_cache.start()
        self.bot.loop.create_task(self.validate_subreddits())

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
                        print(f"[INFO] API rate limit reached, sleeping for {wait:.2f}s")
                        if notify_wait:
                            await notify_wait(wait)  # Notify user of wait time
                        await asyncio.sleep(wait)
                        self.api_calls = 0
                        self.api_reset_time = time.time() + 60

                    self.api_calls += 1
                    self._last_api_call = time.time()
                break  # success, exit the retry loop
            except Exception as e:
                retries += 1
                print(f"[WARNING] API call failed: {e} (retry {retries}/{max_retries})")
                if retries >= max_retries:
                    print("[ERROR] Max retries reached, raising exception")
                    raise
                backoff = 2 ** retries
                print(f"[INFO] Backing off for {backoff}s before retrying...")
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
        print(f"🔄 Subreddit validation complete in {total:.2f}s")
        return report, total

    async def fetch_meme(self, category: str, keyword: Optional[str] = None, notify_wait=None):
        subs = self.subreddits.get(category, [])
        print(f"[DEBUG] fetch_meme: category={category}, keyword={keyword}, subs={subs}")
        if not subs:
            print("[DEBUG] No subs available for category")
            return None

        sub_name = random.choice(subs)
        try:
            await self._throttle_api(notify_wait=notify_wait)  # pass notify_wait here
            subreddit = await self.reddit.subreddit(sub_name, fetch=True)
            print(f"[DEBUG] Picked subreddit: {sub_name}")
        except Exception as e:
            print(f"[ERROR] Could not fetch subreddit '{sub_name}': {e}")
            return None

        await self._throttle_api(notify_wait=notify_wait)  # and here before fetching posts
        posts = [p async for p in subreddit.hot(limit=50) if not p.stickied]
        print(f"[DEBUG] Pulled {len(posts)} hot posts from r/{sub_name}")

        posts = [p for p in posts if self.get_media_url(p)]
        print(f"[DEBUG] {len(posts)} posts have valid media")

        fallback = False
        filtered_posts = posts
        if keyword:
            kw = keyword.lower()
            filtered = [
                p for p in posts
                if kw in (p.title or '').lower() or kw in (str(p.url).lower() if p.url else '')
            ]
            print(f"[DEBUG] {len(filtered)} posts after keyword filter for '{keyword}'")
            if filtered:
                filtered_posts = filtered
            else:
                fallback = True
        if not filtered_posts:
            print("[DEBUG] No posts left after filtering")
            return None

        fresh = [p for p in filtered_posts if p.id not in self.recent_ids]
        print(f"[DEBUG] {len(fresh)} fresh (not recently seen) posts")
        chosen = random.choice(fresh if fresh else filtered_posts)
        self.recent_ids.append(chosen.id)
        if fallback:
            setattr(chosen, 'fallback', True)
        print(f"[DEBUG] Chosen post: {chosen.title} (id: {chosen.id})")
        return chosen

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        msg = reaction.message
        if str(msg.id) in meme_msgs:
            await track_reaction(msg.id, user.id, str(reaction.emoji))

    @commands.hybrid_command(name="meme", description="Fetch a SFW meme")
    async def meme(self, ctx, keyword: Optional[str] = None):
        async def notify_wait(wait_seconds):
            await ctx.send(
                f"⚠️ Bot is rate-limited by Reddit API. Waiting for {wait_seconds:.1f}s before continuing...",
                ephemeral=True
            )
        try:
            await ctx.defer()
            post = await self.fetch_meme('sfw', keyword, notify_wait=notify_wait)
            if not post:
                return await ctx.reply("😔 Couldn't find any memes.", ephemeral=True)
            if getattr(post, 'fallback', False):
                await ctx.send(f"❌ Couldn't find memes for `{keyword}`, here's a random one!")
            media_url = self.get_media_url(post)
            print(f"[DEBUG] Media URL: {media_url}")

            if media_url and (
                media_url.lower().endswith(('.mp4', '.webm', '.gif')) or "v.redd.it" in media_url
            ):
                thumb_url = self.get_video_thumbnail(post)
                embed = Embed(
                    title=post.title,
                    url=f"https://reddit.com{post.permalink}"
                )
                if thumb_url:
                    embed.set_image(url=thumb_url)
                embed.add_field(name="Video Link", value=media_url, inline=False)
                embed.set_footer(text=f"r/{post.subreddit.display_name}")
                msg = await ctx.send(embed=embed)
            else:
                embed = Embed(
                    title=post.title,
                    url=f"https://reddit.com{post.permalink}"
                )
                embed.set_image(url=media_url)
                embed.set_footer(text=f"r/{post.subreddit.display_name}")
                msg = await ctx.send(embed=embed)

            await register_meme_message(
                msg.id,
                ctx.channel.id,
                ctx.guild.id,
                f"https://reddit.com{post.permalink}",
                post.title
            )
        except Exception as e:
            print(f"[ERROR] /meme command error: {e}")
            await ctx.reply("❌ Something went wrong while fetching memes.", ephemeral=True)


    @commands.hybrid_command(name="nsfwmeme", description="Fetch a NSFW meme (NSFW channels only)")
    async def nsfwmeme(self, ctx, keyword: Optional[str] = None):
        async def notify_wait(wait_seconds):
            await ctx.send(
                f"⚠️ Bot is rate-limited by Reddit API. Waiting for {wait_seconds:.1f}s before continuing...",
                ephemeral=True
            )
        try:
            if not ctx.channel.is_nsfw():
                return await ctx.reply("🔞 You can only use NSFW memes in NSFW channels.", ephemeral=True)
            await ctx.defer()
            post = await self.fetch_meme('nsfw', keyword, notify_wait=notify_wait)
            if not post:
                return await ctx.reply("😔 Couldn't find any NSFW memes.", ephemeral=True)
            if getattr(post, 'fallback', False):
                await ctx.send(f"❌ Couldn't find NSFW memes for `{keyword}`, here's a random one!")
            media_url = self.get_media_url(post)
            print(f"[DEBUG] Media URL: {media_url}")

            if media_url and (
                media_url.lower().endswith(('.mp4', '.webm', '.gif')) or "v.redd.it" in media_url
            ):
                thumb_url = self.get_video_thumbnail(post)
                embed = Embed(
                    title=post.title,
                    url=f"https://reddit.com{post.permalink}"
                )
                if thumb_url:
                    embed.set_image(url=thumb_url)
                embed.add_field(name="Video Link", value=media_url, inline=False)
                embed.set_footer(text=f"r/{post.subreddit.display_name}")
                msg = await ctx.send(embed=embed)
            else:
                embed = Embed(
                    title=post.title,
                    url=f"https://reddit.com{post.permalink}"
                )
                embed.set_image(url=media_url)
                embed.set_footer(text=f"r/{post.subreddit.display_name}")
                msg = await ctx.send(embed=embed)

            await register_meme_message(
                msg.id,
                ctx.channel.id,
                ctx.guild.id,
                f"https://reddit.com{post.permalink}",
                post.title
            )
        except Exception as e:
            print(f"[ERROR] /nsfwmeme command error: {e}")
            await ctx.reply("❌ Something went wrong while fetching NSFW memes.", ephemeral=True)


    @commands.hybrid_command(name="r_", description="Fetch a meme from a specific subreddit")
    async def r_(self, ctx, subreddit: str, keyword: Optional[str] = None):
        async def notify_wait(wait_seconds):
            await ctx.send(
                f"⚠️ Bot is rate-limited by Reddit API. Waiting for {wait_seconds:.1f}s before continuing...",
                ephemeral=True
            )
        try:
            await ctx.defer()
            try:
                sub = await self.reddit.subreddit(subreddit, fetch=True)
            except Exception:
                return await ctx.reply(f"❌ Could not find subreddit `{subreddit}`.", ephemeral=True)
            await self._throttle_api(notify_wait=notify_wait)  # Add rate-limit notification before fetching posts
            posts = [p async for p in sub.hot(limit=50) if not p.stickied]
            posts = [p for p in posts if self.get_media_url(p)]
            if not posts:
                return await ctx.reply("😔 No media posts found.", ephemeral=True)
            fallback = False
            if keyword:
                kw = keyword.lower()
                filtered = [
                    p for p in posts
                    if kw in (p.title or '').lower() or kw in (str(p.url).lower() if p.url else '')
                ]
                if filtered:
                    posts = filtered
                else:
                    fallback = True
            chosen = random.choice(posts)
            if fallback:
                await ctx.send(f"❌ Couldn't find any posts for `{keyword}`, here's a random one!")
            media_url = self.get_media_url(chosen)
            print(f"[DEBUG] Media URL: {media_url}")

            if media_url and (
                media_url.lower().endswith(('.mp4', '.webm', '.gif')) or "v.redd.it" in media_url
            ):
                thumb_url = self.get_video_thumbnail(chosen)
                embed = Embed(
                    title=chosen.title,
                    url=f"https://reddit.com{chosen.permalink}"
                )
                if thumb_url:
                    embed.set_image(url=thumb_url)
                embed.add_field(name="Video Link", value=media_url, inline=False)
                embed.set_footer(text=f"r/{chosen.subreddit.display_name}")
                msg = await ctx.send(embed=embed)
            else:
                embed = Embed(
                    title=chosen.title,
                    url=f"https://reddit.com{chosen.permalink}"
                )
                embed.set_image(url=media_url)
                embed.set_footer(text=f"r/{chosen.subreddit.display_name}")
                msg = await ctx.send(embed=embed)

            await register_meme_message(
                msg.id,
                ctx.channel.id,
                ctx.guild.id,
                f"https://reddit.com{chosen.permalink}",
                chosen.title
            )
        except Exception as e:
            print(f"[ERROR] /r_ command error: {e}")
            await ctx.reply("❌ Something went wrong while fetching memes from that subreddit.", ephemeral=True)

    @commands.hybrid_command(name="reloadsubreddits", description="Reload and validate subreddit lists")
    async def reloadsubreddits(self, ctx: commands.Context):
        await ctx.defer(ephemeral=True)
        try:
            report, total = await self.validate_subreddits()
            lines: List[str] = []
            for cat in ('sfw', 'nsfw'):
                total_checked = len(report[cat])
                total_valid = sum(1 for _, status, _ in report[cat] if status == "✅")
                lines.append(f"**{cat.upper()}** ({total_valid}/{total_checked} valid):")
                for name, status, dt in report[cat]:
                    lines.append(f"{status} {name:15} — {dt:.2f}s")
            lines.append(f"**Total:** {total:.2f}s")
            await ctx.send("\n".join(lines), ephemeral=True)   
            sfw_valid = sum(1 for _, status, _ in report['sfw'] if status == "✅")
            sfw_total = len(report['sfw'])
            nsfw_valid = sum(1 for _, status, _ in report['nsfw'] if status == "✅")
            nsfw_total = len(report['nsfw'])
            await ctx.send(
                f"✅ Subreddit lists reloaded and tested! "
                f"({sfw_valid}/{sfw_total} SFW, {nsfw_valid}/{nsfw_total} NSFW)", ephemeral=True
            )   
        except Exception as e:
            await ctx.send("❌ There was an error reloading subreddits.", ephemeral=True)
    
    @commands.hybrid_command(name="topreactions", description="Show top 5 memes by reactions")
    async def topreactions(self, ctx):

        if not meme_msgs:
            return await ctx.reply("No memes have been posted yet!", ephemeral=True)

        # Print all meme_msgs and their reactions for debug
        for msg_id, meta in meme_msgs.items():
            pass

        # Sort meme_msgs by the total number of reactions
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

        await ctx.reply("\n".join(lines), ephemeral=True)

    @commands.hybrid_command(name="memestats", description="Show meme usage stats")
    async def memestats(self, ctx: commands.Context) -> None:
        try:
            total = stats.get('total_memes', 0)
            nsfw_count = stats.get('nsfw_memes', 0)
            kw_counts = stats.get('keyword_counts', {})
            top_kw = max(kw_counts, key=kw_counts.get) if kw_counts else 'N/A'
            await ctx.reply(f"Total: {total} | NSFW: {nsfw_count} | TopKeyword: {top_kw}", ephemeral=True)
        except Exception as e:
            await ctx.reply("❌ Error getting meme stats.", ephemeral=True)

    @commands.hybrid_command(name="topusers", description="Show top meme users")
    async def topusers(self, ctx: commands.Context) -> None:
        users = stats.get('user_counts', {})
        leaderboard = []
        for uid, count in sorted(users.items(), key=lambda x: x[1], reverse=True)[:5]:
            try:
                member = await ctx.guild.fetch_member(int(uid))
                name = member.display_name
            except Exception:
                name = uid
            leaderboard.append(f"{name}: {count}")
        await ctx.reply("\n".join(leaderboard) or "No data", ephemeral=True)

    @commands.hybrid_command(name="topkeywords", description="Show top meme keywords")
    async def topkeywords(self, ctx: commands.Context) -> None:
        kw_counts = stats.get('keyword_counts', {})
        leaderboard = [f"{kw}: {cnt}" for kw, cnt in sorted(
            kw_counts.items(), key=lambda x: x[1], reverse=True)[:5]]
        await ctx.reply("\n".join(leaderboard) or "No data", ephemeral=True)

    @commands.hybrid_command(name="topsubreddits", description="Show top used subreddits")
    async def topsubreddits(self, ctx: commands.Context) -> None:
        sub_counts = stats.get('subreddit_counts', {})
        leaderboard = [f"{sub}: {cnt}" for sub, cnt in sorted(
            sub_counts.items(), key=lambda x: x[1], reverse=True)[:5]]
        await ctx.reply("\n".join(leaderboard) or "No data", ephemeral=True)

    @commands.hybrid_command(name="listsubreddits", description="List current SFW and NSFW subreddits")
    async def listsubreddits(self, ctx: commands.Context) -> None:
        sfw = ", ".join(self.subreddits.get('sfw', [])) or "None"
        nsfw = ", ".join(self.subreddits.get('nsfw', [])) or "None"
        embed = discord.Embed(title="Loaded Subreddits")
        embed.add_field(name="SFW", value=sfw, inline=False)
        embed.add_field(name="NSFW", value=nsfw, inline=False)
        await ctx.reply(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Meme(bot))
