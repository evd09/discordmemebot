import os
import json

DATA_FILE = "data/guild_subreddits.json"
DEFAULTS = {
    "sfw": [
        "memes", "dankmemes", "funny", "wholesomememes",
        "MemeEconomy", "me_irl", "comedyheaven", "AdviceAnimals",
        "memesopdidnotlike", "trashy", "terriblefacebookmemes", "okbuddyretard"
    ],
    "nsfw": [
        "nsfwmemes", "dirtymemes", "gonewild", "NSFW_GIF",
        "SexySexymemes", "lewdanime", "EcchiMemes", "sexmemes",
        "Rule34LoL", "funhornymemes", "spicymemes"
    ]
}

def _load():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def _save(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_guild_subreddits(guild_id, category):
    data = _load()
    gid = str(guild_id)
    if gid in data:
        return data[gid].get(category, DEFAULTS[category].copy())
    else:
        return DEFAULTS[category].copy()

def add_guild_subreddit(guild_id, name, category):
    data = _load()
    gid = str(guild_id)
    if gid not in data:
        data[gid] = { "sfw": DEFAULTS["sfw"].copy(), "nsfw": DEFAULTS["nsfw"].copy() }
    if name not in data[gid][category]:
        data[gid][category].append(name)
    _save(data)

def remove_guild_subreddit(guild_id, name, category):
    data = _load()
    gid = str(guild_id)
    if gid in data and name in data[gid][category]:
        data[gid][category].remove(name)
        _save(data)

def list_guild_subreddits(guild_id, category):
    return get_guild_subreddits(guild_id, category)
