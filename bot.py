# File: bot.py
import os
import asyncio
import pathlib
import discord

from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

async def load_extensions() -> None:
    """
    Dynamically load all cog extensions from the cogs/ directory.
    """
    print("🔍 Starting load_extensions()…")
    for file in pathlib.Path("./cogs").glob("*.py"):
        await bot.load_extension(f"cogs.{file.stem}")

@bot.event
async def on_ready() -> None:
    print(f"🚀 Logged in as {bot.user} (ID: {bot.user.id})")
    print("🔄 Syncing slash commands...")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} commands globally!")
    except Exception as e:
        print(f"❌ Failed to sync slash commands: {e}")

async def main() -> None:
    async with bot:
        await load_extensions()
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
