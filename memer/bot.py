# File: bot.py
import os
from dotenv import load_dotenv

# Load environment variables without crashing on encoding issues.
# Some environments may provide a `.env` file saved with a non UTF-8
# encoding (e.g. Windows-1252).  `load_dotenv` assumes UTF-8 by default and
# raises a ``UnicodeDecodeError`` in that case, preventing the bot from
# starting.  Attempt to load using UTF-8 first and fall back to a more
# permissive single-byte encoding to keep startup functional.
try:  # pragma: no cover - exercised in integration tests
    load_dotenv()
except UnicodeDecodeError:  # pragma: no cover - exercised in integration tests
    load_dotenv(encoding="latin-1")

DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID", "0"))  # Sync commands per Guild ID
DISABLE_GLOBAL_COMMANDS = os.getenv("DISABLE_GLOBAL_COMMANDS", "0") == "1"

import asyncio
import pathlib
import discord
from discord.errors import Forbidden, LoginFailure
from discord import Object
import logging
import importlib

from memer.web.stats_server import start_stats_server
from discord.ext import commands
from types import SimpleNamespace
import yaml
from memer.helpers.guild_subreddits import persist_cache
from memer.helpers import db
from memer import meme_stats

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


def ensure_audio_dirs():
    """Make sure required folders exist before any cogs initialize."""
    os.makedirs("./sounds", exist_ok=True)
    os.makedirs("./data", exist_ok=True)
    os.makedirs("./logs", exist_ok=True)

def load_yaml_config(path="config/cache.yml"):
    if os.path.exists(path):
        with open(path, "r") as f:
            return yaml.safe_load(f)
    return {}

# Inject into bot.config
MEME_CACHE_CONFIG = load_yaml_config().get("meme_cache", {})

# Attach config for cogs (no extra indentation!)
bot.config = SimpleNamespace(
    DEV_GUILD_ID=DEV_GUILD_ID,
    COIN_NAME=COIN_NAME,
    BASE_REWARD=BASE_REWARD,
    KEYWORD_BONUS=KEYWORD_BONUS,
    DAILY_BONUS=DAILY_BONUS,
    MEME_CACHE=MEME_CACHE_CONFIG,
    DISABLE_GLOBAL_COMMANDS=DISABLE_GLOBAL_COMMANDS,
)
# Configure root logger: send to stdout, show INFO+ by default
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)-15s %(message)s",
)

# Configure audiobot logger: send to stdout, show INFO+ by default
logging.getLogger("discord.voice_state").setLevel(logging.INFO)
logging.getLogger("discord.gateway").setLevel(logging.INFO)

# Create module-level logger
log = logging.getLogger(__name__)
async def load_extensions() -> None:
    """
    Dynamically load all cog extensions from the cogs/ directory, including subfolders.
    """
    log.info("🔍 Starting load_extensions()…")

    COGS_DIR = pathlib.Path(__file__).parent / "cogs"
    module_paths = []
    for file in COGS_DIR.rglob("*.py"):
        # Skip non-cog modules
        if (
            file.name == "__init__.py"
            or file.stem in (
                "store",
                "audio_player",
                "audio_queue",
                "audio_events",
                "voice_error_manager",
                "constants",       # 👈 skip constants (no setup())
            )
        ):
            continue

        # Convert file path to dotted module path, e.g., memer/cogs/audio/beep.py -> memer.cogs.audio.beep
        relative = file.relative_to(COGS_DIR).with_suffix("")
        module_paths.append(".".join(["memer", "cogs", *relative.parts]))

    async def _load_one(module_path: str) -> None:
        try:
            await bot.load_extension(module_path)
            log.info("✅ Loaded cog: %s", module_path)
        except Exception as e:
            log.warning("⚠️ Failed to load cog %s: %s", module_path, e)

    await asyncio.gather(*(_load_one(path) for path in module_paths))

async def cleanup_all_voice(bot):
    for guild in bot.guilds:
        try:
            vc = guild.voice_client
            if vc and vc.is_connected():
                log.info(
                    "[STARTUP CLEANUP] Disconnecting from voice in %s (%s)...",
                    guild.name,
                    guild.id,
                )
                await vc.disconnect(force=True)
        except Exception as e:
            log.error(
                "[STARTUP CLEANUP ERROR] %s: %s",
                guild.name,
                e,
            )


async def sync_app_commands(bot: commands.Bot) -> None:
    """Sync application commands to the dev guild (if configured)."""

    # Diagnostic
    cmds = bot.tree.get_commands()
    log.info(
        "Found %d application commands to sync: %s", len(cmds), [c.name for c in cmds]
    )

    # Clear all commands to avoid lingering/deprecated entries
    bot.tree.clear_commands(guild=None)
    for cmd in cmds:
        bot.tree.add_command(cmd)

    guild_obj = None
    if DEV_GUILD_ID:
        guild_obj = discord.Object(id=DEV_GUILD_ID)
        bot.tree.clear_commands(guild=guild_obj)
        if DISABLE_GLOBAL_COMMANDS:
            log.info(
                "Copying commands into dev guild %s; global commands disabled", DEV_GUILD_ID
            )
            bot.tree.copy_global_to(guild=guild_obj)
        else:
            log.info(
                "Skipping copy_global_to for dev guild %s; using global commands",
                DEV_GUILD_ID,
            )

    if not DEV_GUILD_ID:
        log.info("No DEV_GUILD_ID provided; skipping dev guild sync")
        return

    log.info("🔄 Syncing slash commands to dev guild…")
    try:
        synced = await bot.tree.sync(guild=guild_obj)
        log.info("✅ Synced %d commands to dev guild %s!", len(synced), DEV_GUILD_ID)
    except Forbidden:
        log.warning("Dev‑guild sync forbidden; continuing with global sync later…")
    except Exception:
        log.error("❌ Failed to sync dev guild commands", exc_info=True)

    # Fetch global commands after syncing to ensure deprecated commands were removed
    try:
        global_cmds = await bot.tree.fetch_commands()
        seen_names = {}
        seen_ids = set()
        for cmd in global_cmds:
            if cmd.id in seen_ids or (
                cmd.name in seen_names and seen_names[cmd.name] != cmd.id
            ):
                try:
                    await bot.http.delete_global_command(bot.application_id, cmd.id)
                    log.info("🗑️ Removed duplicate global command %s (%s)", cmd.name, cmd.id)
                except Exception:
                    log.error(
                        "Failed to delete duplicate global command %s (%s)",
                        cmd.name,
                        cmd.id,
                        exc_info=True,
                    )
                continue
            seen_ids.add(cmd.id)
            seen_names[cmd.name] = cmd.id

        global_names = set(seen_names)
        expected_names = {cmd.name for cmd in cmds}
        log.info("🌐 Commands currently registered globally: %s", sorted(global_names))
        leftover = global_names - expected_names
        if leftover:
            log.warning(
                "Unwanted global commands remain after sync; manual removal may be required: %s",
                sorted(leftover),
            )
    except Exception:
        log.error("Failed to fetch global commands after sync", exc_info=True)

    if DEV_GUILD_ID:
        guild = bot.get_guild(DEV_GUILD_ID)
        if guild is None:
            log.warning(
                "Dev guild %s not accessible; skipping fetch_commands",
                DEV_GUILD_ID,
            )
        else:
            guild_obj = Object(id=DEV_GUILD_ID)
            try:
                cmds_in_guild = await bot.tree.fetch_commands(guild=guild_obj)
                log.info(
                    "⚙️ Commands currently in dev guild %s: %s",
                    DEV_GUILD_ID,
                    [c.name for c in cmds_in_guild],
                )
            except Forbidden:
                log.warning(
                    "Forbidden to fetch commands in dev guild %s; skipping",
                    DEV_GUILD_ID,
                )

@bot.event
async def on_ready() -> None:
    await cleanup_all_voice(bot)

    log.info(f"🚀 Logged in as {bot.user} (ID: {bot.user.id})")
    log.info("Bot is in guilds: %s", [g.id for g in bot.guilds])
    log.info("DEV_GUILD_ID = %s", DEV_GUILD_ID)

    # First sync commands to the dev guild (if configured)
    await sync_app_commands(bot)

    # Remove any legacy commands before syncing globally
    bot.tree.remove_command("ping")

    try:
        synced = await bot.tree.sync()
        log.info("✅ Synced %d commands globally!", len(synced))
    except Exception:
        log.error("❌ Failed to globally sync slash commands", exc_info=True)


async def main() -> None:
    async with bot:
        ensure_audio_dirs()
        await db.init()
        await meme_stats.init()
        await start_stats_server()
        await load_extensions()
        events = importlib.import_module("memer.cogs.audio.audio_events")
        await events.setup(bot)
        try:
            await bot.start(TOKEN)
        except (LoginFailure, TypeError):
            log.error(
                "Invalid or missing DISCORD_TOKEN. Set a valid token before starting the bot."
            )
    # Persist guild subreddit cache after the bot has shut down
    await db.close()
    await meme_stats.close()
    persist_cache()

if __name__ == "__main__":
    asyncio.run(main())
