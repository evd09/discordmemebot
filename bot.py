import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from reddit_meme import get_meme
from meme_stats import update_stats, stats
import asyncio
import logging
import asyncpraw
import time
import sqlite3
import json
import aiohttp

logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
APPLICATION_ID = int(os.getenv("APPLICATION_ID"))

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, application_id=APPLICATION_ID)
tree = bot.tree

# Database setup
conn = sqlite3.connect("cache.db")
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS meme_cache (
    key TEXT PRIMARY KEY,
    data TEXT,
    timestamp REAL
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS user_cooldowns (
    user_id TEXT PRIMARY KEY,
    expires_at REAL
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS subreddit_cache (
    type TEXT PRIMARY KEY,
    data TEXT,
    timestamp REAL
)
""")
conn.commit()

# Rate limiting and cache utils
CACHE_DURATION = 300  # seconds
COOLDOWN_SECONDS = 10

def is_on_cooldown(user_id):
    now = time.time()
    c.execute("SELECT expires_at FROM user_cooldowns WHERE user_id = ?", (str(user_id),))
    row = c.fetchone()
    return bool(row and row[0] > now)


def set_cooldown(user_id):
    expires = time.time() + COOLDOWN_SECONDS
    c.execute(
        "REPLACE INTO user_cooldowns (user_id, expires_at) VALUES (?, ?)",
        (str(user_id), expires)
    )
    conn.commit()

# Subreddit cache utils

def load_subreddit_cache():
    c.execute("SELECT data FROM subreddit_cache WHERE type='nsfw'")
    row = c.fetchone()
    nsfw = json.loads(row[0]) if row else []
    c.execute("SELECT data FROM subreddit_cache WHERE type='sfw'")
    row = c.fetchone()
    sfw = json.loads(row[0]) if row else []
    return nsfw, sfw


def save_subreddit_cache(sfw, nsfw):
    now = time.time()
    c.execute(
        "REPLACE INTO subreddit_cache (type, data, timestamp) VALUES (?, ?, ?)",
        ('sfw', json.dumps(sfw), now)
    )
    c.execute(
        "REPLACE INTO subreddit_cache (type, data, timestamp) VALUES (?, ?, ?)",
        ('nsfw', json.dumps(nsfw), now)
    )
    conn.commit()

# Root commands
@tree.command(name="ping", description="Ping the bot to see if it's alive")
async def ping_command(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong!")

@tree.command(name="reloadsubreddits", description="Reload and validate subreddit lists")
@app_commands.guilds(discord.Object(id=int(GUILD_ID)))
async def reload_subreddits(interaction: discord.Interaction):
    await interaction.response.defer()
    cog = bot.get_cog("MemeBot")
    if cog:
        await cog.validate_subreddits()
        await interaction.followup.send("✅ Subreddits reloaded.")
    else:
        await interaction.followup.send("❌ Cog not loaded.")

class MemeBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reddit = asyncpraw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent=os.getenv("REDDIT_USER_AGENT")
        )
        self.nsfw_subreddits, self.sfw_subreddits = load_subreddit_cache()

    async def cog_load(self):
        await self.validate_subreddits()

    async def fetch_external_subreddits(self):
        url = "https://raw.githubusercontent.com/BigHikes/reddit-meme-subreddits/main/subreddits.json"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    data = await resp.json()
                    return data.get("sfw", []), data.get("nsfw", [])
        except:
            return [], []

    async def validate_subreddits(self):
        static_sfw = ["memes","wholesomememes","dankmemes","funny","MemeEconomy","me_irl","comedyheaven","AdviceAnimals"]
        static_nsfw = ["nsfwmemes","dirtymemes","pornmemes","memesgonewild","rule34memes","lewdanime","EcchiMemes"]
        ext_sfw, ext_nsfw = await self.fetch_external_subreddits()
        sfw_list = list(set(static_sfw+ext_sfw))
        nsfw_list = list(set(static_nsfw+ext_nsfw))
        self.sfw_subreddits, self.nsfw_subreddits = [], []
        for sub in sfw_list:
            try:
                await self.reddit.subreddit(sub, fetch=True)
                self.sfw_subreddits.append(sub)
            except:
                pass
        for sub in nsfw_list:
            try:
                await self.reddit.subreddit(sub, fetch=True)
                self.nsfw_subreddits.append(sub)
            except:
                pass
        save_subreddit_cache(self.sfw_subreddits, self.nsfw_subreddits)
        # Log loaded subreddit lists
        print(f"🗒️ Loaded SFW subreddits: {', '.join(self.sfw_subreddits) or 'None'}")
        print(f"🗒️ Loaded NSFW subreddits: {', '.join(self.nsfw_subreddits) or 'None'}")

    @app_commands.command(name="meme", description="Fetch a SFW meme by keyword")
    @app_commands.guilds(discord.Object(id=int(GUILD_ID)))
    async def meme(self, interaction: discord.Interaction, keyword: str):
        await interaction.response.defer()
        if is_on_cooldown(interaction.user.id):
            return await interaction.followup.send("⏳ Cooldown active.", ephemeral=True)
        set_cooldown(interaction.user.id)

        post = await get_meme(self.reddit, self.sfw_subreddits, keyword, False)
        # ← bump stats *only* on a successful fetch
        update_stats(interaction.user.id, keyword, post.subreddit.display_name, False)
        if not post:
            return await interaction.followup.send(
                f"❌ No meme found for `{keyword}`, and I couldn’t find any fallback either.",
                ephemeral=True
            )

        # did this actually match the keyword?
        title_lower = post.title.lower()
        url_lower   = post.url.lower()
        if keyword.lower() not in title_lower and keyword.lower() not in url_lower:
            # fallback
            await interaction.followup.send(
                f"❌ Couldn't find a meme for `{keyword}`, here's a random one:"
            )

        embed = discord.Embed(title=post.title, url=post.url)
        embed.set_image(url=post.url)
        await interaction.followup.send(embed=embed)


    @app_commands.command(name="nsfwmeme", description="Fetch a NSFW meme by keyword")
    @app_commands.guilds(discord.Object(id=int(GUILD_ID)))
    async def nsfwmeme(self, interaction: discord.Interaction, keyword: str):
        if not interaction.channel.is_nsfw():
            return await interaction.response.send_message("🔞 NSFW channels only.", ephemeral=True)

        await interaction.response.defer()
        if is_on_cooldown(interaction.user.id):
            return await interaction.followup.send("⏳ Cooldown active.", ephemeral=True)
        set_cooldown(interaction.user.id)

        post = await get_meme(self.reddit, self.nsfw_subreddits, keyword, True)
        # ← bump NSFW stat
        update_stats(interaction.user.id, keyword, post.subreddit.display_name, True)
        if not post:
            return await interaction.followup.send(
                f"❌ No NSFW meme found for `{keyword}`, and I couldn’t find any fallback either.",
                ephemeral=True
            )

        title_lower = post.title.lower()
        url_lower   = post.url.lower()
        if keyword.lower() not in title_lower and keyword.lower() not in url_lower:
            await interaction.followup.send(
                f"❌ Couldn't find a NSFW meme for `{keyword}`, here's a random one:"
            )

        embed = discord.Embed(title=post.title, url=post.url)
        embed.set_image(url=post.url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="memestats", description="Show meme usage stats")
    @app_commands.guilds(discord.Object(id=int(GUILD_ID)))
    async def memestats(self, interaction: discord.Interaction):
        # Directly send stats
        await interaction.response.send_message(
            f"Total: {stats['total_memes']} | NSFW: {stats['nsfw_memes']} | TopKeyword: {max(stats['keyword_counts'], default='N/A')}",
            ephemeral=True
        )

    @app_commands.command(name="topusers", description="Show top meme users")
    @app_commands.guilds(discord.Object(id=int(GUILD_ID)))
    async def topusers(self, interaction: discord.Interaction):
        leaderboard = []
        for uid, count in sorted(stats['user_counts'].items(), key=lambda x:x[1], reverse=True)[:5]:
            member = await interaction.guild.fetch_member(int(uid)) if uid.isdigit() else None
            name = member.display_name if member else 'Unknown'
            leaderboard.append(f"{name}: {count}")
        await interaction.response.send_message("\n".join(leaderboard) or "No data", ephemeral=True)

    @app_commands.command(name="topkeywords", description="Show top meme keywords")
    @app_commands.guilds(discord.Object(id=int(GUILD_ID)))
    async def topkeywords(self, interaction: discord.Interaction):
        leaderboard = [f"{kw}: {count}" for kw,count in sorted(stats['keyword_counts'].items(), key=lambda x:x[1], reverse=True)[:5]]
        await interaction.response.send_message("\n".join(leaderboard) or "No data", ephemeral=True)

    @app_commands.command(name="topsubreddits", description="Show top used subreddits")
    @app_commands.guilds(discord.Object(id=int(GUILD_ID)))
    async def topsubreddits(self, interaction: discord.Interaction):
        leaderboard = [f"{sub}: {count}" for sub,count in sorted(stats['subreddit_counts'].items(), key=lambda x:x[1], reverse=True)[:5]]
        await interaction.response.send_message("\n".join(leaderboard) or "No data", ephemeral=True)

    @app_commands.command(name="listsubreddits", description="Show loaded SFW and NSFW subreddits")
    @app_commands.guilds(discord.Object(id=int(GUILD_ID)))
    async def listsubreddits(self, interaction: discord.Interaction):
        """List currently loaded subreddit names for SFW and NSFW"""
        sfw_list = ", ".join(self.sfw_subreddits) or "None"
        nsfw_list = ", ".join(self.nsfw_subreddits) or "None"
        embed = discord.Embed(title="Loaded Subreddits")
        embed.add_field(name="SFW", value=sfw_list, inline=False)
        embed.add_field(name="NSFW", value=nsfw_list, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Sync commands on_ready
auth_event = False
@bot.event
async def on_ready():
    global auth_event
    if auth_event:
        return
    auth_event = True
    print(f"🚀 Bot is ready: {bot.user}")
    # Sync slash commands once
    print("🔄 Syncing slash commands...")
    try:
        synced = await tree.sync(guild=discord.Object(id=int(GUILD_ID)))
        print(f"✅ Synced {len(synced)} slash command(s) to server {GUILD_ID}")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

# Graceful shutdown handlers
import signal
async def shutdown():
    print("🛑 Shutting down gracefully...")
    # Close Reddit client
    cog = bot.get_cog("MemeBot")
    if cog and hasattr(cog, 'reddit'):
        try:
            await cog.reddit.close()
        except Exception:
            pass
    # Close DB connection
    try:
        conn.close()
    except Exception:
        pass
    await bot.close()

async def _run():
    print("🧠 Loading MemeBot Cog...")
    await bot.add_cog(MemeBot(bot))
    print("✅ MemeBot Cog loaded.")

    # Start the bot (login & connect)
    print("🔑 Logging in and connecting to Discord...")
    await bot.start(TOKEN)


def run_bot():
    loop = asyncio.get_event_loop()
    # Register signal handlers for graceful shutdown
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        except NotImplementedError:
            pass
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()

if __name__ == '__main__':
    run_bot()
import signal

async def shutdown():
    print("🛑 Shutting down gracefully...")
    # Close Reddit client
    cog = bot.get_cog("MemeBot")
    if cog and hasattr(cog, 'reddit'):
        try:
            await cog.reddit.close()
        except Exception:
            pass
    # Close DB connection
    try:
        conn.close()
    except Exception:
        pass
    await bot.close()

async def _run():
    print("🧠 Loading MemeBot Cog...")
    await bot.add_cog(MemeBot(bot))
    print("✅ MemeBot Cog loaded.")

    # Start the bot (login & connect)
    print("🔑 Logging in and connecting to Discord...")
    await bot.start(TOKEN)


def run_bot():
    loop = asyncio.get_event_loop()
    # Register signal handlers for graceful shutdown
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
        except NotImplementedError:
            pass
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()

if __name__ == '__main__':
    run_bot()
