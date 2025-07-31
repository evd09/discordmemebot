# Changelog

# Version 3.0 #

### Added ### 
Economy & Rewards features added.
Games & gambling features added.
Feature to disable all Economy, Rewards, and gambling features. /toggle_gambling >>> Need to have admin rights on the server.

# Version 2.5 #

1. Replaced print() Debugs with Structured Logging
- Introduced a module‑level log = logging.getLogger(__name__) in both bot.py and cogs/meme.py.
- Swapped all ad‑hoc print() calls for the appropriate log.debug(), log.info(), log.warning(), or log.error(..., exc_info=True) calls.
- Configured the root logger in bot.py with logging.basicConfig(level=logging.INFO, …), so you can toggle verbosity globally without touching cog code.

2. Fixed Background Cache Pruning
- Removed duplicate _prune_cache definitions and the old _do_prune_cache helper.
- Kept a single, @tasks.loop(seconds=60)‑decorated _prune_cache method.
- In __init__, initialized self.cache = {}, then simply called self._prune_cache.start().
- Ensured self._prune_cache.cancel() in cog_unload().

3. Added Utility Commands
- /help – A hybrid command that lists all available MemeBot commands in a neat embed, wrapped in a try/except to log any unexpected errors.
- /ping – Reports the bot’s current Discord gateway latency in milliseconds.
- /uptime – Calculates and displays how long the bot has been running since self.start_time.

4. Disabled Default Help Command
- Updated bot = commands.Bot(...) in bot.py to include help_command=None, which unregisters Discord.py’s built‑in help so your custom /help can register without conflict.

5. Added /dashboard & HTTP Stats Endpoint
- /dashboard – A new hybrid command that reads your existing stats.json and renders a Discord embed showing:
	- Total memes served
	- NSFW meme count
	- Top 3 users by usage
	- Top 3 subreddits by usage
	- Top 3 keywords by count
- HTTP /stats endpoint – A lightweight aiohttp server in bot.py serves stats.json at http://<your‑host>:8080/stats for external dashboards or integrations.

6. Cleanup & Consistency
- Ensured every slash command follows the same pattern: @commands.hybrid_command, clear docstring, try/except with log.error(..., exc_info=True), and an ephemeral reply for errors.
- Logged key milestones (e.g. cog initialization, subreddit list load, validation complete, dashboard generation) at INFO level.
