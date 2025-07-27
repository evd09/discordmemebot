import json
import os

STATS_FILE = "stats.json"

if os.path.exists(STATS_FILE):
    with open(STATS_FILE, "r") as f:
        stats = json.load(f)
else:
    stats = {
        "total_memes": 0,
        "nsfw_memes": 0,
        "keyword_counts": {},
        "user_counts": {},
        "subreddit_counts": {}
    }

def save_stats():
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)

def update_stats(user_id, keyword, subreddit, nsfw=False):
    stats["total_memes"] += 1
    if nsfw:
        stats["nsfw_memes"] += 1

    keyword = keyword.lower()
    stats["keyword_counts"][keyword] = stats["keyword_counts"].get(keyword, 0) + 1
    stats["user_counts"][str(user_id)] = stats["user_counts"].get(str(user_id), 0) + 1
    stats["subreddit_counts"][subreddit] = stats["subreddit_counts"].get(subreddit, 0) + 1

    save_stats()
