Discord Meme Bot

A versatile Discord bot that fetches and serves memes from Reddit based on user keywords, with support for both SFW and NSFW content. Features caching, cooldowns, subreddit validation, and fallback mechanisms to ensure reliable results.

🚀 Key Features

Keyword-driven meme search: Fetch memes by keyword or emoji, with whole-word and substring matching.

Dual listing coverage: Searches both hot and best listings (100 posts each) for broad results.

SFW & NSFW modes: Separate /meme and /nsfwmeme commands; NSFW requires channel to be marked NSFW.

Automatic fallback: If no matching meme is found, a random fallback post is served to avoid empty responses.

User cooldowns & caching: Per-user cooldown (default 10s) and meme result caching (default 5min) in SQLite (cache.db).

Subreddit validation: Dynamically fetches and validates SFW/NSFW subreddit lists from a remote JSON, with local caching.

Usage statistics: Tracks total memes, NSFW count, top keywords, users, and subreddits in stats.json with /memestats, /topusers, /topkeywords, /topsubreddits commands.

Graceful shutdown: Cleans up Reddit client and database connection on exit.

Emoji & punctuation handling: Supports emoji searches and strips punctuation so "dont" matches "Don't" titles.

Slash commands: Fully implemented with Discord's application commands and guild-scoped syncing.

📦 Requirements

Python 3.11+

Discord Bot Token & Application ID

Reddit API credentials (Client ID, Client Secret, User Agent)

Docker (optional for containerized deployment)

Python Dependencies

discord.py
asyncpraw
python-dotenv
PyNaCl

🔧 Setup & Configuration

1. Clone the repository:
git clone https://github.com/evd09/memebot.git
cd discord-meme-bot

2. **Environment variables**:

Create a `.env` in the project root:
DISCORD_TOKEN=your_discord_bot_token
APPLICATION_ID=your_discord_application_id
GUILD_ID=your_test_guild_id
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USER_AGENT=discord:meme.bot:v1 (by /u/YourRedditUsername)

3. Install dependencies:
pip install --no-cache-dir -r requirements.txt

4. **Run locally**:
python bot.py

🐳 Docker
Build the image:
docker build -t discord-meme-bot .

Run the container:
docker run -it --env-file .env discord-meme-bot

Docker Tips
Bind mounting: Persist stats.json and cache.db outside the container:
docker run -v /host/path/meme-data:/app -it --env-file .env discord-meme-bot

- **.dockerignore**: Exclude data files:
```ignore
stats.json
cache.db

⚠️ Rate Limits & Best Practices

Reddit API rate limit: 60 requests/minute (can vary). Avoid overly large limit values in listings/search.

Default searches scan 200 posts per subreddit (100 hot + 100 best)—adjust as needed.

Do not set limit=None or excessively high values to prevent hitting rate limits.

Leverage caching (cache.db) to minimize repeated searches for the same keyword.

Respect NSFW channel restrictions to comply with community guidelines.

🛠️ Commands Overview

Command

Description

/meme <keyword>

Fetch a SFW meme by keyword or emoji

/nsfwmeme <keyword>

Fetch a NSFW meme (NSFW channel required)

/listsubreddits

List loaded SFW & NSFW subreddit sources

/memestats

Show total memes, NSFW ratio, top keyword

/topusers

Leaderboard of top meme requesters

/topkeywords

Top-used search keywords

/topsubreddits

Most-used subreddit sources

/reloadsubreddits

Force refresh & validation of subreddit lists

/ping

Health check (bot alive)

🎉 Contributing & Testing

Create issues or PRs for bug fixes and enhancements.

Run a local test server (set GUILD_ID) to verify slash commands sync.

Ensure environment variables are set before running.

Happy memeing! 😄
