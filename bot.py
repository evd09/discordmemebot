# File: bot.py
import os
from dotenv import load_dotenv

load_dotenv()
DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID", "0"))  # Sync commands per Guild ID

import asyncio
import pathlib
import discord
from discord.errors import Forbidden 
from discord import Object
import logging
from aiohttp import web
import json
from discord.ext import commands
from types import SimpleNamespace  

TOKEN        = os.getenv("DISCORD_TOKEN")
COIN_NAME    = os.getenv("COIN_NAME", "coins")
BASE_REWARD  = int(os.getenv("BASE_REWARD", 10))
KEYWORD_BONUS= int(os.getenv("KEYWORD_BONUS", 5))
DAILY_BONUS  = int(os.getenv("DAILY_BONUS", 50))

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="/",
    help_command=None,
    intents=intents
)

# Attach config for cogs (no extra indentation!)
bot.config = SimpleNamespace(
    DEV_GUILD_ID=DEV_GUILD_ID,
    COIN_NAME=COIN_NAME,
    BASE_REWARD=BASE_REWARD,
    KEYWORD_BONUS=KEYWORD_BONUS,
    DAILY_BONUS=DAILY_BONUS
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
        name = file.stem
        if name == "store":
            continue  
        await bot.load_extension(f"cogs.{file.stem}")
        log.info("✅ Loaded cog: %s", name)

async def stats_handler(request):
    with open("stats.json", "r") as f:
        data = json.load(f)
    return web.json_response(data)

@bot.event
async def on_ready() -> None:
    log.info(f"🚀 Logged in as {bot.user} (ID: {bot.user.id})")
    log.info("Bot is in guilds: %s", [g.id for g in bot.guilds])
    log.info("DEV_GUILD_ID = %s", DEV_GUILD_ID)

    # Diagnostic
    cmds = bot.tree.get_commands()
    log.info("Found %d application commands to sync: %s", len(cmds), [c.name for c in cmds])

    # ── Step 2: copy globals (no await) ──
    if DEV_GUILD_ID:
        log.info("Copying global commands into dev guild %s…", DEV_GUILD_ID)
        guild_obj = discord.Object(id=DEV_GUILD_ID)
        bot.tree.copy_global_to(guild=guild_obj)

    log.info("🔄 Syncing slash commands…")
    try:
        if DEV_GUILD_ID:
            synced = await bot.tree.sync(guild=guild_obj)
            log.info("✅ Synced %d commands to dev guild %s!", len(synced), DEV_GUILD_ID)
        else:
            synced = await bot.tree.sync()
            log.info("✅ Synced %d commands globally!", len(synced))
    except Forbidden:
        log.warning("Dev‑guild sync forbidden; falling back to global…")
        synced = await bot.tree.sync()
        log.info("✅ Synced %d commands globally!", len(synced))
    except Exception:
        log.error("❌ Failed to sync slash commands", exc_info=True)

    if DEV_GUILD_ID:
        guild_obj = Object(id=DEV_GUILD_ID)
        cmds_in_guild = await bot.tree.fetch_commands(guild=guild_obj)
        log.info(
            "⚙️ Commands currently in dev guild %s: %s",
            DEV_GUILD_ID,
            [c.name for c in cmds_in_guild]
        )

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
