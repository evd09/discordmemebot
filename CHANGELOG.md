# Changelog

# Version 5.1 #

- `/entrance` UI now displays your current entrance and updates when changed.
- Removed standalone `/myentrance` command; resync global commands after updating.

# Version 5.0 #

- Removed standalone `/ping` and `/uptime` commands; their functionality now lives in the `/memeadmin` interface.
- After upgrading, resync your global commands so the changes take effect.

# Version 4.0 #
Voice & Audio Features in MemeBot

All new voice features are managed by slash commands — no file edits needed!

- Removed `/listbeeps` and `/listsubreddits`; `/help` now shows available beep sounds and subreddit lists.

📂 Folders & Setup
- sounds/ — Place general sound files (for /beeps and other effects).
- entrances/ — Place custom user entrance audio/video clips here.

Both folders are auto-mounted via Docker. Supported: mp3, wav, m4a, mp4 (audio only), etc.
🎤 Entrance Sound System
1️⃣ Assign or Change Entrance Sound
/entrance
- Full UI lets you choose, preview, and set your entrance clip from the available files.
- Admins can set for others.
2️⃣ Preview Any Sound
- Use the /entrance command and click Preview in the menu.
3️⃣ Remove or Adjust Volume
- Use /entrance and select “Remove” or adjust volume with the slider.

🔊 Beep & Soundboard
Browse or Play Beeps
/beeps

See Available Beeps
/help

🏃‍♂️ What Happens When You Join Voice?
- If you have an entrance sound, bot joins, plays your clip (with volume you set), then leaves automatically.
- Supports both audio and video (extracts audio).
- All files are cached for faster play.

⚡ Advanced Controls (Admins)
- Set any user’s entrance:
- /setentrance <user> <filename>
- UI supports fuzzy search, clickable file previews, and safe ephemeral (only you see) controls.
- Limit on max cache size: /cacheinfo shows current audio cache.

💡 Tips
- File not showing? Make sure it’s in the right folder and has a supported extension.
- UI not working? Refresh Discord or try the command again.
- Volume too low/high? Use the slider in the /entrance UI.
All changes are instant. No bot restart needed!

# Version 3.0 #

### Added ### 
- Economy & Rewards features added.
- Gambling games features added.
- Feature to disable all Economy, Rewards, and gambling features. /toggle_gambling
	- Need to have admin rights on the server.

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
