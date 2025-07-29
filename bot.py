# File: bot.py
import os
from dotenv import load_dotenv

load_dotenv()
DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID", "0")) #Sync commands per Guild ID

import asyncio
import pathlib
import discord
from discord.errors import Forbidden 
import logging
from aiohttp import web
import json
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix="/",
    help_command=None,
    intents=intents
)

# Configure root logger: send to stdout, show INFO+ by default
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)-15s %(message)s",
)
# Create module-level logger
log = logging.getLogger(__name__)

async def load_extensions() -> None:
    """
    Dynamically load all cog extensions from the cogs/ directory.
    """
    log.info("🔍 Starting load_extensions()…")
    for file in pathlib.Path("./cogs").glob("*.py"):
        await bot.load_extension(f"cogs.{file.stem}")

async def stats_handler(request):
    with open("stats.json", "r") as f:
        data = json.load(f)
    return web.json_response(data)

@bot.event
async def on_ready() -> None:
    log.info(f"🚀 Logged in as {bot.user} (ID: {bot.user.id})")
    # Diagnostic: list every guild the bot is in
    log.info("Bot is in guilds: %s", [g.id for g in bot.guilds])
    log.info("DEV_GUILD_ID = %s", DEV_GUILD_ID)

    log.info("🔄 Syncing slash commands...")
    try:
        if DEV_GUILD_ID:
            guild = discord.Object(id=DEV_GUILD_ID)
            synced = await bot.tree.sync(guild=guild)
            log.info(f"✅ Synced {len(synced)} commands to dev guild {DEV_GUILD_ID}!")
        else:
            synced = await bot.tree.sync()
            log.info(f"✅ Synced {len(synced)} commands globally!")
    except Forbidden:
        log.warning("Guild‑sync Forbidden (Missing Access); falling back to global sync")
        synced = await bot.tree.sync()
        log.info(f"✅ Synced {len(synced)} commands globally!")
    except Exception:
        log.error("❌ Failed to sync slash commands", exc_info=True)

app = web.Application()
app.router.add_get("/stats", stats_handler)

async def start_web():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    log.info("Stats HTTP server running on port 8080")

async def main() -> None:
    async with bot:
        await start_web()  
        await load_extensions()
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
