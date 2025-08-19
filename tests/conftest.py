import sys
import types
from types import SimpleNamespace

# Stub asyncpraw and its models.Submission
asyncpraw = types.ModuleType("asyncpraw")
asyncpraw.models = types.ModuleType("asyncpraw.models")
class Submission:
    pass
asyncpraw.models.Submission = Submission
sys.modules.setdefault("asyncpraw", asyncpraw)
sys.modules.setdefault("asyncpraw.models", asyncpraw.models)

# Stub discord with Embed and errors.NotFound and ext.commands.Context
discord_stub = types.ModuleType("discord")

class Embed:
    def __init__(self, **kwargs):
        self.title = kwargs.get("title")
        self.image = SimpleNamespace(url=None)

    def set_image(self, *, url):
        self.image.url = url

class NotFound(Exception):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)

discord_stub.Embed = Embed
discord_stub.errors = SimpleNamespace(NotFound=NotFound)

ext_module = types.ModuleType("discord.ext")
commands_module = types.ModuleType("discord.ext.commands")
commands_module.Context = object
ext_module.commands = commands_module

discord_stub.ext = ext_module

sys.modules.setdefault("discord", discord_stub)
sys.modules.setdefault("discord.ext", ext_module)
sys.modules.setdefault("discord.ext.commands", commands_module)
