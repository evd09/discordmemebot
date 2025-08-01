import os
import sqlite3
from subreddits import SFW_SUBREDDITS, NSFW_SUBREDDITS

DB_PATH = "meme_stats.db"

def get_db():
    return sqlite3.connect(DB_PATH)

def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        # General stats
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER DEFAULT 0
            )
        """)
        # User meme counts
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_counts (
                user_id TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        """)
        # Keyword meme counts
        cur.execute("""
            CREATE TABLE IF NOT EXISTS keyword_counts (
                keyword TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        """)
        # Subreddit meme counts
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subreddit_counts (
                subreddit TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        """)
        # Meme message registry
        cur.execute("""
            CREATE TABLE IF NOT EXISTS meme_msgs (
                message_id TEXT PRIMARY KEY,
                channel_id TEXT,
                guild_id TEXT,
                url TEXT,
                title TEXT
            )
        """)
        # Meme message reactions
        cur.execute("""
            CREATE TABLE IF NOT EXISTS meme_reactions (
                message_id TEXT,
                emoji TEXT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (message_id, emoji)
            )
        """)
        conn.commit()

# --- Subreddits ---

def init_subreddit_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subreddits (
                name TEXT PRIMARY KEY,
                category TEXT CHECK(category IN ('sfw', 'nsfw')) NOT NULL,
                enabled INTEGER DEFAULT 1
            )
        """)
        cur.execute("SELECT COUNT(*) FROM subreddits")
        if cur.fetchone()[0] == 0:
            for sub in SFW_SUBREDDITS:
                cur.execute("INSERT INTO subreddits (name, category, enabled) VALUES (?, 'sfw', 1)", (sub,))
            for sub in NSFW_SUBREDDITS:
                cur.execute("INSERT INTO subreddits (name, category, enabled) VALUES (?, 'nsfw', 1)", (sub,))
        conn.commit()

def get_subreddits(category):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM subreddits WHERE category = ? AND enabled = 1", (category,))
        return [row[0] for row in cur.fetchall()]

def add_subreddit(name, category):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO subreddits (name, category, enabled) VALUES (?, ?, 1)",
            (name, category)
        )
        cur.execute(
            "UPDATE subreddits SET enabled = 1, category = ? WHERE name = ?",
            (category, name)
        )
        conn.commit()

def remove_subreddit(name):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE subreddits SET enabled = 0 WHERE name = ?",
            (name,)
        )
        conn.commit()

# --- STATS ---

def get_stat(key):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM stats WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else 0

def set_stat(key, value):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO stats (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

def inc_stat(key, by=1):
    v = get_stat(key)
    set_stat(key, v + by)

def get_all_stats():
    stats = {}
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM stats")
        for k, v in cur.fetchall():
            stats[k] = v
    return stats

# --- Update stats (main entrypoint for bot) ---

def update_stats(user_id, keyword, subreddit, nsfw=False):
    inc_stat("total_memes", 1)
    if nsfw:
        inc_stat("nsfw_memes", 1)

    keyword = (keyword or "").lower()
    with get_db() as conn:
        cur = conn.cursor()
        # Keyword
        cur.execute("INSERT INTO keyword_counts (keyword, count) VALUES (?, 1) ON CONFLICT(keyword) DO UPDATE SET count = count + 1", (keyword,))
        # User
        cur.execute("INSERT INTO user_counts (user_id, count) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET count = count + 1", (str(user_id),))
        # Subreddit
        cur.execute("INSERT INTO subreddit_counts (subreddit, count) VALUES (?, 1) ON CONFLICT(subreddit) DO UPDATE SET count = count + 1", (subreddit,))
        conn.commit()

# --- User, keyword, and subreddit leaderboards ---

def get_top_users(limit=5):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, count FROM user_counts ORDER BY count DESC LIMIT ?", (limit,))
        return cur.fetchall()

def get_top_keywords(limit=5):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT keyword, count FROM keyword_counts ORDER BY count DESC LIMIT ?", (limit,))
        return cur.fetchall()

def get_top_subreddits(limit=5):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT subreddit, count FROM subreddit_counts ORDER BY count DESC LIMIT ?", (limit,))
        return cur.fetchall()

# --- Meme message and reaction tracking ---

def get_meme_msgs():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM meme_msgs")
        return cur.fetchall()

async def register_meme_message(message_id, channel_id, guild_id, url, title):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO meme_msgs (message_id, channel_id, guild_id, url, title)
            VALUES (?, ?, ?, ?, ?)
        """, (str(message_id), str(channel_id), str(guild_id), url, title))
        conn.commit()

async def track_reaction(message_id, user_id, emoji):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO meme_reactions (message_id, emoji, count) VALUES (?, ?, 1)
            ON CONFLICT(message_id, emoji) DO UPDATE SET count = count + 1
        """, (str(message_id), emoji))
        conn.commit()

def get_reactions_for_message(message_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT emoji, count FROM meme_reactions WHERE message_id = ?", (str(message_id),))
        return dict(cur.fetchall())

def get_top_reacted_memes(limit=5):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT m.message_id, m.url, m.title, m.guild_id, m.channel_id, 
                   IFNULL(SUM(r.count), 0) as total_reactions
            FROM meme_msgs m
            LEFT JOIN meme_reactions r ON m.message_id = r.message_id
            GROUP BY m.message_id
            HAVING total_reactions > 0
            ORDER BY total_reactions DESC
            LIMIT ?
        """, (limit,))
        return cur.fetchall()

# --- Export for dashboard etc ---

def get_dashboard_stats():
    stats = get_all_stats()
    users = dict(get_top_users(100))
    subs = dict(get_top_subreddits(100))
    kws = dict(get_top_keywords(100))
    return {
        "total_memes": stats.get("total_memes", 0),
        "nsfw_memes": stats.get("nsfw_memes", 0),
        "user_counts": users,
        "subreddit_counts": subs,
        "keyword_counts": kws
    }

# --- Init on import ---
init_db()
init_subreddit_db()
