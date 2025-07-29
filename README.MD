# Discord Meme Bot #

A versatile Discord bot that fetches and serves memes from Reddit based on user keywords, supporting both SFW and NSFW content. It includes advanced features such as keyword-driven search, caching with cooldowns, dynamic subreddit validation, intelligent fallback mechanisms, and enhanced API rate limit handling with user notifications ensuring fast, reliable, and user-friendly meme delivery.

---

## 🚀 Key Features ##
- Keyword-driven meme search: Fetch memes by keyword or emoji, supporting whole-word and substring matching.
- Dual listing coverage: Searches hot listings for broad results with smart caching.
- SFW & NSFW modes: Separate `/meme` and `/nsfwmeme` commands; NSFW requires channel to be marked NSFW.
- Fetch memes from any subreddit: New `/r_` command to fetch memes from specific subreddits with optional keyword filtering.
- Automatic fallback: If no matching meme is found, a random fallback post is served to avoid empty responses.
- User cooldowns & caching: Per-user cooldown (default 10s) and meme result caching (default 5min) to reduce API calls.
- Subreddit validation: Dynamically fetches and validates SFW/NSFW subreddit lists from a remote JSON, with local fallback.
- Usage statistics: Tracks total memes, NSFW count, top keywords, users, and subreddits in `stats.json` with `/memestats`, `/topusers`, `/topkeywords`, `/topsubreddits`.
- Reaction tracking: Tracks meme message reactions to support leaderboard with `/topreactions`.
- Rate limit awareness: Smart handling of Reddit API limits with exponential backoff, retries, and user notifications on delays.
- Graceful shutdown: Cleans up Reddit client and database connection on exit.
- Emoji & punctuation handling: Supports emoji searches and strips punctuation so "dont" matches "Don't" titles.
- Slash commands: Fully implemented with Discord's application commands and guild-scoped syncing.

---

## 📁 File Structure ##
```
discord-meme-bot/
├── cogs/
│   └── meme.py                # Main meme cog with commands and API integration
├── meme_stats.py              # Meme stats and tracking utilities
├── bot.py                     # Main bot entrypoint and Discord setup
├── Dockerfile                 # Docker build instructions
├── docker-compose.yml         # Docker Compose service configuration
├── .env                       # Environment variables for bot and Reddit API keys
├── requirements.txt           # Python dependencies list
├── stats.json                 # Persistent meme stats file (volume mounted)
├── cache.db                   # Persistent meme cache database (volume mounted)
└── subreddits.json            # Cached subreddit lists (volume mounted)
```
---

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

---

## 🔧 Setup & Configuration ##

1. Clone the repository:
```bash
   git clone https://github.com/evd09/memebot.git
   cd discord-meme-bot
```
2. **Environment variables**:
Create a `.env` in the project root:
```
DISCORD_TOKEN=your_discord_bot_token
APPLICATION_ID=your_discord_application_id
GUILD_ID=your_test_guild_id
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USER_AGENT=discord:meme.bot:v1 (by /u/YourRedditUsername)
```
3. Install dependencies:
```
pip install --no-cache-dir -r requirements.txt
```
4. **Run locally**:
```
python bot.py
```
## 🐳 Docker ##
Build the image:
```
docker build -t discord-meme-bot .
```
Run the container Basic interactive run with environment variables:
```
docker run -it --env-file .env discord-meme-bot
```

###OR###

##Docker Compose##
1. Place your .env file in the same directory as docker-compose.yml.
2. Run in the directory of docker-compose.yml
```
docker-compose up -d
```

### Docker Tips ###
Bind mounting: Persist stats.json and cache.db outside the container:
```
docker run -v /host/path/meme-data:/app -it --env-file .env discord-meme-bot
```
- **.dockerignore**: Exclude data files:
```ignore
stats.json
cache.db
```

## ⚠️ Rate Limits & Best Practices ##
- Reddit API rate limit: ~60 requests/minute (varies). The bot enforces smart throttling with user notifications.
- Default searches scan 50 posts per subreddit to avoid rate limits.
- Do not set excessively high limit values.
- Caching and cooldowns minimize repeated searches.
- Respect NSFW channel restrictions as per Discord guidelines.

## 🛠️ Commands Overview ##
| Command                   | Description                                                          |
|:--------------------------|:---------------------------------------------------------------------|
| /meme <keyword>           | Fetch a SFW meme by keyword or emoji                                 |
| /nsfwmeme <kw>            | Fetch a NSFW meme (NSFW channel required)                            |
| /r_ <subreddit> [keyword] | Fetch meme from a specific subreddit, optionally filtered by keyword | 
| /topreactions             | Show top 5 memes by reaction counts                                  |
| /ping                     | Health check (bot alive)                                             |  
| /listsubreddits           | List loaded SFW & NSFW subreddit sources                             |
| /memestats                | Show total memes, NSFW ratio, top keyword                            |
| /topusers                 | Leaderboard of top meme requesters                                   |
| /topsubreddits            | Most-used subreddit sources                                          |
| /reloadsubreddits         | Force refresh & validation of subreddit lists                        |

## 🎉 Contributing & Testing ##
- Open issues or PRs for improvements.
- Use a test guild (GUILD_ID) to verify slash command syncing.
- Ensure .env is configured before running.

Happy memeing! 😄 
