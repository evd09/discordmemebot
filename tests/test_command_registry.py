import asyncio
import logging
import pathlib
import sys

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from memer import bot as bot_module


def test_expected_slash_commands():
    async def runner():
        await bot_module.load_extensions()
        cmd_names = {c.name for c in bot_module.bot.tree.get_commands()}
        unexpected = cmd_names - bot_module.EXPECTED_SLASH_COMMANDS
        missing = bot_module.EXPECTED_SLASH_COMMANDS - cmd_names
        if unexpected:
            logging.warning(
                "Unexpected commands detected: %s", sorted(unexpected)
            )
        assert not unexpected and not missing, (
            f"Unexpected commands: {unexpected} Missing commands: {missing}"
        )
        gamble = bot_module.bot.get_cog("Gamble")
        if gamble:
            await gamble.store.close()

    asyncio.run(runner())
