import json
import os

STATS_FILE = "stats.json"
MEME_MSGS_FILE = "meme_messages.json"   # NEW: file to track meme posts

# --- Default structure for stats ---
DEFAULT_STATS = {
    "total_memes": 0,
    "nsfw_memes": 0,
    "keyword_counts": {},
    "user_counts": {},
    "subreddit_counts": {},
    "reactions": {}
}

# --- Load stats from file or use defaults ---
if os.path.exists(STATS_FILE):
    try:
        with open(STATS_FILE, "r") as f:
            stats = json.load(f)
    except Exception:
        stats = DEFAULT_STATS.copy()
else:
    stats = DEFAULT_STATS.copy()

# Ensure all keys are present (in case of a partial/corrupted file)
for key, val in DEFAULT_STATS.items():
    if key not in stats:
        stats[key] = val

def save_stats():
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)

def update_stats(user_id, keyword, subreddit, nsfw=False):
    stats["total_memes"] += 1
    if nsfw:
        stats["nsfw_memes"] += 1

    keyword = (keyword or '').lower()
    stats["keyword_counts"][keyword] = stats["keyword_counts"].get(keyword, 0) + 1
    stats["user_counts"][str(user_id)] = stats["user_counts"].get(str(user_id), 0) + 1
    stats["subreddit_counts"][subreddit] = stats["subreddit_counts"].get(subreddit, 0) + 1

    save_stats()

# --- Meme message tracking ---

if os.path.exists(MEME_MSGS_FILE):
    try:
        with open(MEME_MSGS_FILE, "r") as f:
            meme_msgs = json.load(f)
    except Exception:
        meme_msgs = {}
else:
    meme_msgs = {}  # message_id: {channel_id, guild_id, url, title, reactions: {}}

def save_meme_msgs():
    with open(MEME_MSGS_FILE, "w") as f:
        json.dump(meme_msgs, f, indent=2)

async def register_meme_message(message_id, channel_id, guild_id, url, title):
    meme_msgs[str(message_id)] = {
        "channel_id": str(channel_id),
        "guild_id": str(guild_id),
        "url": url,
        "title": title,
        "reactions": {}  # emoji: count
    }
    save_meme_msgs()

async def track_reaction(message_id, user_id, emoji):
    msgid = str(message_id)
    if msgid in meme_msgs:
        meme_msgs[msgid]["reactions"][emoji] = meme_msgs[msgid]["reactions"].get(emoji, 0) + 1
        save_meme_msgs()


async def track_reaction(message_id, user_id, emoji):
    msgid = str(message_id)
    if msgid in meme_msgs:
        meme_msgs[msgid]["reactions"][emoji] = meme_msgs[msgid]["reactions"].get(emoji, 0) + 1
        save_meme_msgs()
