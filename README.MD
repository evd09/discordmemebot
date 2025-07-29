# Discord Meme Bot 2.5 #

A versatile Discord bot that fetches and serves memes from Reddit based on user keywords, supporting both SFW and NSFW content. It includes advanced features such as keyword-driven search, caching with cooldowns, dynamic subreddit validation, intelligent fallback mechanisms, and enhanced API rate limit handling with user notifications ensuring fast, reliable, and user-friendly meme delivery.

---

## 🚀 Key Features ##
- Keyword-driven meme search: Fetch memes by keyword or emoji, supporting whole-word and substring matching.
- Dual listing coverage: Searches hot listings for broad results with smart caching.
- SFW & NSFW modes: Separate `/meme` and `/nsfwmeme` commands; NSFW requires channel to be marked NSFW.
- Subreddit‑specific fetch: /r_ <subreddit> [keyword] for custom sources with fallback to random.
- Automatic fallback: If no matching meme is found, a random fallback post is served to avoid empty responses.
- Caching & cooldowns: Per‑user 10 s cooldown and 5 min cache to reduce API calls.
- Subreddit validation: Dynamically fetches and validates SFW/NSFW subreddit lists from a remote JSON, with local fallback.
- Usage statistics: Tracks total memes, NSFW count, top keywords, users, and subreddits in `stats.json` with `/memestats`, `/topusers`, `/topkeywords`, `/topsubreddits`.
- Reaction tracking: Tracks meme message reactions to support leaderboard with `/topreactions`.
- Dynamic subreddit validation: Reload and verify lists at runtime.
- Graceful shutdown: Cleans up Reddit client and database connection on exit.
- Utility commands: /help, /ping, /uptime, /dashboard.
- HTTP stats endpoint: Exposes raw stats at /stats for external tools.

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
- aiosqlite

---
## Discord Bot Permissions: ##
### Recommended Bot Permissions: ###
| Permission                      | Purpose                                                |
| ------------------------------- | ------------------------------------------------------ |
| **Send Messages**               | To post memes and replies in channels                  |
| **Embed Links**                 | To send rich embeds (titles, images, video thumbnails) |
| **Read Message History**        | To access message context if needed                    |
| **Use Slash Commands**          | To allow slash command invocation                      |
| **Add Reactions**               | To add emoji reactions for meme voting or feedback     |
| **Read Messages/View Channels** | To access messages and channels where it’s used        |

### Optional (based on features): ###
| Permission                     | Purpose                                                                            |
| ------------------------------ | ---------------------------------------------------------------------------------- |
| **Manage Messages**            | To delete or manage memes/messages if you implement moderation or cleanup features |
| **Manage Emojis and Stickers** | If you want to add custom reactions or emojis                                      |
| **Send TTS Messages**          | If your bot uses text-to-speech features                                           |

---

## Running Locally ##

1. Clone the repository:
```bash
git clone https://github.com/evd09/discordmemebot.git
cd discordmemebot
```
2. **Environment variables**:
Create a `.env` in the project root:
```
sudo nano .env
```
```
DISCORD_TOKEN=your_discord_bot_token
APPLICATION_ID=your_discord_application_id
GUILD_ID=your_test_guild_id
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USER_AGENT=discord:meme.bot:v1 (by /u/YourRedditUsername)
```
   - Create an [Reddit API application](https://www.reddit.com/prefs/apps).

3. Create cogs directory and move meme.py to cogs/
```
mkdir cogs
mv meme.py cogs/
```
4. Create stat.JSON & subreddits.json
```
touch subreddits.json
touch stats.json
chmod 666 stats.json  # (optional, for write permission)
```
5. Install dependencies:
```
pip install --no-cache-dir -r requirements.txt
```
6. Run the bot:
```
python bot.py
```
## 🐳 Docker ##
### Docker CLI ###
1. Create directory for config files
```
mkdir discordmemebot
cd discordmemebot
```
2. Create stat.JSON & subreddits.json & .env
```
touch subreddits.json
touch stats.json
chmod 666 stats.json  # (optional, for write permission)
touch subreddits.json # (optional, for write permission)
```
```
sudo nano .env
```
```
DISCORD_TOKEN=your_discord_bot_token
APPLICATION_ID=your_discord_application_id
GUILD_ID=your_test_guild_id
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USER_AGENT=discord:meme.bot:v1 (by /u/YourRedditUsername)
```
3. Pull the image:
```
sudo docker pull ghcr.io/evd09/memebot:latest
```
4. Run the container
```
sudo docker run -d \
  --name memebot \
  --env-file .env \
  -v /full/path/to/stats.json:/app/stats.json \
  -v /full/path/to/cache.db:/app/cache.db \
  ghcr.io/evd09/memebot:latest
```
	** OR **
```
sudo docker pull ghcr.io/evd09/memebot:latest && docker run -d --name memebot --env-file .env -v "$(pwd)/stats.json":/app/stats.json -v "$(pwd)/cache.db":/app/cache.db ghcr.io/evd09/memebot:latest

```
### Docker Compose ###
1. Create directory for config files
```
mkdir discordmemebot
cd discordmemebot
```
2. Create stat.JSON & subreddits.json & .env
```
touch subreddits.json
touch stats.json
chmod 666 stats.json
chmod 666 subreddits.json
```
```
sudo nano .env
```
3. Place the following and update credentials
```
DISCORD_TOKEN=your_discord_bot_token
APPLICATION_ID=your_discord_application_id
GUILD_ID=your_test_guild_id
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USER_AGENT=discord:meme.bot:v1 (by /u/YourRedditUsername)
```
2. Create a docker-compose.yml
```
sudo nano docker-compose.yml
```
```
services:
  memebot:
    image: ghcr.io/evd09/memebot:latest
    container_name: memebot
    env_file: .env
    restart: unless-stopped
    volumes:
      # Persist usage stats & cache
      - ./stats.json:/app/stats.json
      - ./cache.db:/app/cache.db
	  - ./subreddits.json:/app/subreddits.json

    # (Optional) Expose ports if your bot uses webhooks, etc.
    # ports:
    #   - "3000:3000"
```
3. Fetch latest image and start memebot
```
sudo docker compose pull memebot   
sudo docker compose up -d memebot 
```
---
## 📝 How to Add More Subreddits to `subreddits.json`
1. **Locate the `subreddits.json` file**
   - On your host machine (outside Docker), find the `subreddits.json` file in your project directory.  
     ```
     ls -l subreddits.json
     ```

2. **Open the file in a text editor**
   - Use your preferred editor (VSCode, nano, vim, etc):
     ```
     nano subreddits.json
     ```
     or  
     ```
     code subreddits.json
     ```

3. **Edit the lists**
   - Inside, you'll see a structure like this:
     ```json
     {
       "sfw": [
         "memes", "dankmemes", "wholesomememes", "me_irl", "funny"
       ],
       "nsfw": [
         "nsfwmemes", "sexymemes", "rule34memes"
       ]
     }
     ```
   - **Add or remove subreddit names** (as strings) inside the `"sfw"` or `"nsfw"` lists.  
     Example: Add `"historymemes"` to SFW, and `"spicymemes"` to NSFW.
     ```json
     {
       "sfw": [
         "memes", "dankmemes", "wholesomememes", "me_irl", "funny", "historymemes"
       ],
       "nsfw": [
         "nsfwmemes", "sexymemes", "rule34memes", "spicymemes"
       ]
     }
     ```
   - **Tip:** Each subreddit should be in quotes, separated by commas.
   - The more subreddits you add to the list, the longer it will take for the bot to query each one, which may increase the chance of hitting Reddit’s API rate limiters.
   - You can check you JSON file with [JSON validator](https://jsonlint.com/).

4. **Save the file**
   - If using `nano`, press `Ctrl+O` to write, then `Enter`, and `Ctrl+X` to exit.

5. **(If using Docker) Make sure the file is mounted into your container**
   - Your `docker-compose.yml` or `docker run` command should have:
     ```
     - ./subreddits.json:/app/subreddits.json
     ```
   - This ensures changes on the host are seen inside the running container.

6. **Reload subreddits in the bot**
   - Use the `/reloadsubreddits` command in your Discord server **OR** restart your bot for the changes to take effect.
     ```
     /reloadsubreddits
     ```
   - The bot should reply with the updated validation info.

7. **Verify**
   - Try `/meme` or `/nsfwmeme` with your new subreddits/keywords to check!

### ⚠️ Important Notes ###
- Double-check your JSON formatting! A single missing comma or quote will break loading.
- Only add public, active subreddits. NSFW subs **must** go in `"nsfw"`, SFW in `"sfw"`.
- If the bot reports a problem loading or validating, check your `subreddits.json` for typos or formatting errors.

That’s it! You can now easily expand your meme sources any time. 🎉
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
| /ping						| Health check (bot latency)										   |
| /uptime					| Show how long the bot has been running							   |
| /dashboard				| Show meme usage dashboard in Discord embed						   |

## 🎉 Contributing & Testing ##
- Open issues or PRs for improvements.
- Use a test guild (GUILD_ID) to verify slash command syncing.
- Ensure .env is configured before running.

Happy memeing! 😄 
