# MemeBot 4.0 — Audio, Entrances & Beeps Update #
---
## NOTE ##
MemeBot 4.0 requires discord.py version: 2.6.0a5239+g4496df79
This fixes Discord 4006 session errors (audio/voice bugs) that affect all current stable versions when joining voice channels.
## ❤️ Credits & Notes ##
- Special thanks to the Discord.py team, Reddit API maintainers, and everyone reporting bugs for Discord 4006!
- If you run into voice errors, always check your library version and update this repo for the latest fixes.
- Dockerfile includes this requirements.
---

## 🎤 Audio, Entrance, and Beep System — Major Additions ##

- User-assigned entrance sounds (per user, with volume control)
- Interactive /entrance UI: Discord Views, dropdown file search, volume control, preview, and save — all in one ephemeral message
- Interactive /beeps command: Browse or randomly play beep SFX
- Live voice channel playback (via FFmpeg) for both entrances and beeps
- Preview before save: Test your entrance sound/volume as much as you want
- Voice join/leave and audio error handling: Full support for Discord’s quirks (including 4006+ error auto-retry and cooldown logic)
- Ephemeral UI: All interactive audio commands use ephemeral responses — only you see your settings
- Admin Tools: /setentrance <user> <filename> and /reloadentrances for admins
- Log file rotation/cleanup: Old/large logs are deleted automatically
- Slash command autocomplete: For entrance files
---
## 💡 Upgrading from v3.x ##
- New sounds/entrances/ and sounds/beeps/ folders are required for audio features
- entrance_sounds.json is auto-managed
- Older meme/economy/gambling features still work — just add your API keys as before
--- 
## 📁 File Structure ##
```
memebot/
├── bot.py				   # Main bot entrypoint and Discord setup
├── cogs/
│   └── audio/
│       ├── audio_player.py         	   # Audio playback, RAM caching, and FFmpeg logic
│       ├── audio_queue.py          	   # Smart queueing and cooldowns for all audio
│       ├── beep.py               	   # /beeps and /listbeeps commands
│       ├── entrance.py             	   # /entrance UI View (set, preview, save, remove)
│       ├── constants.py                   # Folder paths and config
│	│   ├── audio_admin.py 		   # audio admin commands 
│	│   ├── audio_events.py	           # Handles audio-related Discord bot events.
│	│   └── voice_error_manager.py     # Manages errors during voice playback.
│	│
│	├── meme.py                	   # Main meme cog with commands and API integration
│	├── gambling.py                    # Defines Discord commands for placing bets, playing games (like Blackjack), and handling wager logic 
│	└── economy.py            	   # Provides core economy commands (e.g., balance checks, daily rewards) and interfaces with the store
│
├── helpers/
│   └── store.py               		   # Abstracts read/write operations to the economy database (adds/removes user funds, queries balances) 
│
├── data/
│   └── entrance_sounds.json               # User entrance assignments (auto-managed)
│   └── economy.db             		   # SQLite database file storing all user balances, transaction history, and economy settings 
│
├── sounds/
│   ├── beeps/                    	   # Random beep SFX files
│   └── entrances/                	   # Assignable entrance files (audio/video)
│
├── logs/
│   ├── entrance.log
│	├── audio.log 
│   └── beep.log
│
├── meme_stats.py              		  # Tracks meme usage, rewards, and statistics.
├── reddit_meme.py                        # Fetches Reddit posts and extracts media.
├── logger_setup.py	              	  # Shared rotating logger
├── log_cleanup.py                	  # Scheduled log cleaner (optional)
├── config.json                   	  # (Optional) for cache settings etc.
├── .env                          	  # (Optional) for tokens/secrets
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
└── subreddits.py            		  # Stores and manages SFW/NSFW subreddit lists.
```
---

## Setup Folders ##

- Place beep sounds in sounds/beeps/
- Place entrance files in sounds/entrances/
	- (mp3, wav, ogg, mp4, webm supported)
	

## 📦 Requirements ##
- Python 3.11+
- Discord Bot Token & Application ID
- Reddit API credentials (Client ID, Client Secret, User Agent)
- Docker (optional for containerized deployment)

### Python Dependencies ###
- discord.py
- asyncpraw
- python-dotenv
- PyNaCl
- aiosqlite

---
## Discord Bot Permissions: ##
| Permission               | Purpose                                  |
| ------------------------ | ---------------------------------------- |
| **Send Messages**        | To post memes/replies                    |
| **Embed Links**          | To send rich embeds (images, video)      |
| **Use Slash Commands**   | To allow modern slash commands           |
| **Read Message History** | For user/guild stats                     |
| **Add Reactions**        | For meme voting                          |
| **Connect/Speak**        | For voice channel entrance/beep playback |


---

## 🐳 Docker Deployment for MemeBot ##
### 1. Create directory for config files ###
```
mkdir discordmemebot
cd discordmemebot
```
### 2. Create Required Folders and .env File ###
```
mkdir sounds data logs
mkdir -p sounds/entrances
mkdir -p sounds/beeps
nano .env
```
```
DISCORD_TOKEN=your_discord_bot_token
APPLICATION_ID=your_discord_application_id
DEV_GUILD_ID=your_test_guild_id    # Optional, only for testing in your server
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USER_AGENT=discord:meme.bot:v1 (by /u/YourRedditUsername)
COIN_NAME=Memes 💎                # e.g. "Gold", "Shards", "Points"

# Reward amounts
BASE_REWARD=10
KEYWORD_BONUS=5
DAILY_BONUS=50

# Optional: audio cache limit
MAX_CACHE_SIZE=100
```
**Tip: Make sure you don’t have spaces around the = and remove any # comments from actual lines.**
### 3. Run with Docker CLI ###
```
sudo docker pull ghcr.io/evd09/memebot:latest
```
**Start the bot:**
```
sudo docker run -d --name memebot \
  --env-file .env \
  -v "$(pwd)/sounds":/app/sounds \
  -v "$(pwd)/data":/app/data \
  -v "$(pwd)/logs":/app/logs \
  ghcr.io/evd09/memebot:latest

```
### 4. Or Use Docker Compose (Recommended for Easy Updates) ###
```
services:
  memebot:
    image: ghcr.io/evd09/memebot:latest
    container_name: memebot
    env_file: .env
    restart: unless-stopped
    volumes:
      - ./data:/app/data
      - ./sounds:/app/sounds
      - ./logs:/app/logs
    # ports:
    #   - "3000:3000"  # Optional: if you add a web UI, etc.
  
```
**Start the bot:**
```
sudo docker compose pull
sudo docker compose up -d
```
**To upgrade:**
```
sudo docker compose down
sudo docker compose pull
sudo docker compose up -d
```
---
## 📝 How to Add or Remove Subreddits ##
### Use Slash Commands (Recommended) ###
Subreddits are now managed live using Discord slash commands. 
	- Changes are stored persistently in subreddits.py (not subreddits.json), and are available immediately no need to restart the bot!

**Add a Subreddit**
- /addsubreddit <name> <sfw|nsfw>
	- Example:
		- /addsubreddit historymemes sfw
		- /addsubreddit spicymemes nsfw
**Remove a Subreddit**
- /removesubreddit <name>
	- Example:
		- /removesubreddit spicymemes
**See Current Lists**
- /listsubreddits
	- Shows the current SFW and NSFW subreddits loaded.
**Validate Subreddits**
- /validatesubreddits
	- Checks if each subreddit actually exists and is reachable.
---
**⚠️ Static subreddits.py on Reboot**
- Subreddit lists are loaded from subreddits.py when the bot starts.
- Newly added or removed subreddits are saved persistently, but if you edit subreddits.py manually, you must restart the bot for changes to take effect.
- Do not edit subreddits.json directly anymore—it is not used.
**Tips & Notes**
- There’s no more need to manually edit any JSON files for subreddit management.
- /addsubreddit and /removesubreddit work instantly and safely.
- For advanced editing (rarely needed), you can modify subreddits.py directly, but a bot restart is required to reload.
---
### ⚠️ Important Notes/🆘 Troubleshooting  ###
- Double-check your JSON formatting! A single missing comma or quote will break loading.
- Only add public, active subreddits. NSFW subs **must** go in `"nsfw"`, SFW in `"sfw"`.
- If the bot reports a problem loading or validating, check your `subreddits.json` for typos or formatting errors.
- 4006/voice join errors?
	- Double-check your discord.py version is 2.6.0a5239+g4496df79 or newer!
- Audio not playing?
	- Confirm your bot has "Connect" and "Speak" permissions in Discord
	- Use /entrance and /beeps in a real voice channel, not DM
	- All logs are in /logs/, check for details
- File not found?
	- Check file permissions and paths for sounds/entrances/ and sounds/beeps/
	- File extension (e.g., .mp3, .wav) must match
---
## ⚠️ Rate Limits & Best Practices ##
- Reddit API rate limit: ~60 requests/minute (varies). The bot enforces smart throttling with user notifications.
- Default searches scan 50 posts per subreddit to avoid rate limits.
- Do not set excessively high limit values.
- Caching and cooldowns minimize repeated searches.
- Respect NSFW channel restrictions as per Discord guidelines.

## 🛠️ Commands Overview ##
| Command                   | Description                                                          |
|:--------------------------|:---------------------------------------------------------------------|
| /help 					| List all commands													   |
| /meme <keyword>           | Fetch a SFW meme by keyword or emoji                                 |
| /nsfwmeme <kw>            | Fetch a NSFW meme (NSFW channel required)                            |
| /r_ <subreddit> [keyword] | Fetch meme from a specific subreddit, optionally filtered by keyword |
| /dashboard                | Show meme and economy stats & leaderboards                           |
| /ping                     | Health check (bot alive)                                             |
| /listsubreddits           | List loaded SFW & NSFW subreddit sources                             |
| /reloadsubreddits         | Force refresh & validation of subreddit lists                        |
| /ping						| Health check (bot latency)										   |
| /uptime					| Show how long the bot has been running							   |
| /toggle_gambling enable:	| Enable or Disable Economy, Rewards, and gambling features			   |
| /balance          		| Check your coin balance			                                   |
| /buy <item> 				| Purchase a shop item  PlaceHolder									   |
| /gamble flip <amount>     | Interactive coin flip                                   			   |
| /gamble roll <amount>     | Interactive dice roll                                                |
| /gamble highlow <amount>  | Interactive high-low card                             			   |
| /gamble slots <amount>    | Spin the slots                              						   |
| /gamble crash <amount>    | Crash game — cash out before it blows                                |
| /gamble blackjack <amount>| Interactive blackjack                                          	   |
| /gamble lottery           | Enter today's 10-coin lottery                        				   |

### Entrance/Beeps
| Command                 | Description                               |
| ----------------------- | ----------------------------------------- |
| /entrance               | **Interactive UI**: Set, preview, remove  |
| /myentrance             | Show your entrance file/volume            |
| /setentrance <user> <f> | Admin: Set entrance for any user          |
| /cacheinfo              | Show RAM audio cache count                |
| /beeps                  | Play a random beep or choose one          |
| /listbeeps              | List all beep files                       |


## 🎉 Contributing & Testing ##
- Open issues or PRs for improvements.
- Use a test guild (GUILD_ID) to verify slash command syncing.
- Ensure .env is configured before running.


Happy memeing! 😄 


