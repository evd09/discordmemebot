import os
import aiosqlite
import time
import asyncio
import logging
from datetime import date

log = logging.getLogger(__name__)
DB_PATH = "data/economy.db"

class Store:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        # Open a single connection we can reuse throughout the lifetime of the bot
        async def _open_db():
            return await aiosqlite.connect(self.db_path)
        self._db_task = asyncio.create_task(_open_db())

    async def _db(self) -> aiosqlite.Connection:
        """Return the shared connection, awaiting its creation if needed."""
        return await self._db_task

    async def close(self):
        db = await self._db()
        await db.close()

    async def _with_retry(self, fn, *args, **kwargs):
        """Simple 3-attempt retry with exponential backoff."""
        for attempt in range(1, 4):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                log.warning("DB op failed (attempt %d/3): %s", attempt, e, exc_info=True)
                await asyncio.sleep(0.1 * 2 ** (attempt - 1))
        log.error("DB op permanently failed after 3 attempts", exc_info=True)
        raise

    async def init(self):
        """Initialize all tables."""
        async def _init():
            db = await self._db()
            # balances
            await db.execute("""
            CREATE TABLE IF NOT EXISTS balances (
              user_id TEXT PRIMARY KEY,
              coins   INTEGER NOT NULL DEFAULT 0
            );
            """)
            # transactions
            await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
              id        INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id   TEXT NOT NULL,
              delta     INTEGER NOT NULL,
              reason    TEXT,
              timestamp INTEGER NOT NULL
            );
            """)
            # daily bonus claims
            await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_claims (
              user_id   TEXT PRIMARY KEY,
              last_date TEXT NOT NULL
            );
            """)
            # lottery entries
            await db.execute("""
            CREATE TABLE IF NOT EXISTS lottery_entries (
              user_id   TEXT PRIMARY KEY,
              last_date TEXT NOT NULL
            );
            """)
            # per-guild settings
            await db.execute("""
            CREATE TABLE IF NOT EXISTS server_settings (
              guild_id          TEXT PRIMARY KEY,
              gambling_enabled  INTEGER NOT NULL DEFAULT 1
            );
            """)
            await db.commit()
        await self._with_retry(_init)

    async def update_balance(self, user_id: str, delta: int, reason: str):
        ts = int(time.time())
        async def _upd():
            db = await self._db()
            # upsert balance
            await db.execute("""
              INSERT INTO balances(user_id, coins) VALUES(?,?)
              ON CONFLICT(user_id) DO UPDATE
                SET coins = balances.coins + excluded.coins;
            """, (user_id, delta))
            # log transaction
            await db.execute("""
              INSERT INTO transactions(user_id, delta, reason, timestamp)
              VALUES (?,?,?,?);
            """, (user_id, delta, reason, ts))
            await db.commit()
        await self._with_retry(_upd)

    async def get_balance(self, user_id: str) -> int:
        async def _get():
            db = await self._db()
            cur = await db.execute(
                "SELECT coins FROM balances WHERE user_id=?", (user_id,)
            )
            row = await cur.fetchone()
            return row[0] if row else 0
        return await self._with_retry(_get)

    async def get_top_balances(self, limit: int = 5):
        db = await self._db()
        cur = await db.execute(
            "SELECT user_id, coins FROM balances ORDER BY coins DESC LIMIT ?",
            (limit,)
        )
        return await cur.fetchall()

    async def try_daily_bonus(self, user_id: str, bonus: int) -> bool:
        today = date.today().isoformat()
        db = await self._db()
        cur = await db.execute(
            "SELECT last_date FROM daily_claims WHERE user_id=?", (user_id,)
        )
        row = await cur.fetchone()
        if row and row[0] == today:
            return False
        # record claim
        await db.execute("""
          INSERT INTO daily_claims(user_id, last_date) VALUES(?,?)
          ON CONFLICT(user_id) DO UPDATE SET last_date=excluded.last_date;
        """, (user_id, today))
        # award coins
        await db.execute("""
          INSERT INTO balances(user_id, coins) VALUES(?,?)
          ON CONFLICT(user_id) DO UPDATE SET coins = balances.coins + excluded.coins;
        """, (user_id, bonus))
        await db.commit()
        return True

    async def try_lottery(self, user_id: str) -> bool:
        today = date.today().isoformat()
        db = await self._db()
        cur = await db.execute(
            "SELECT last_date FROM lottery_entries WHERE user_id=?", (user_id,)
        )
        row = await cur.fetchone()
        if row and row[0] == today:
            return False
        await db.execute("""
          INSERT INTO lottery_entries(user_id, last_date) VALUES(?,?)
          ON CONFLICT(user_id) DO UPDATE SET last_date=excluded.last_date;
        """, (user_id, today))
        await db.commit()
        return True

    async def get_transactions(self, user_id: str, limit: int = 10):
        db = await self._db()
        cur = await db.execute("""
            SELECT delta, reason, timestamp
              FROM transactions
             WHERE user_id = ?
          ORDER BY timestamp DESC
             LIMIT ?
        """, (user_id, limit))
        return await cur.fetchall()

    async def get_win_loss_counts(self, user_id: str):
        games = {
            "Coin Flip": "flip",
            "Dice Roll": "Rolled",
            "High-Low":  "HighLow",
            "Slots":     "Slots",
            "Crash":     "Crash x",
            "Blackjack": "Blackjack"
        }
        stats = {}
        db = await self._db()
        for label, patt in games.items():
            cur = await db.execute(f"""
                SELECT
                  SUM(CASE WHEN delta>0 THEN 1 ELSE 0 END),
                  SUM(CASE WHEN delta<0 THEN 1 ELSE 0 END)
                  FROM transactions
                 WHERE user_id = ?
                   AND reason LIKE ?
            """, (user_id, f"%{patt}%"))
            w, l = await cur.fetchone()
            stats[label] = (w or 0, l or 0)
        return stats

    # ─── per-guild toggle methods ────────────────────────────────────────────────

    async def is_gambling_enabled(self, guild_id: str) -> bool:
        """Return True if gambling is enabled in this guild (default on)."""
        db = await self._db()
        cur = await db.execute("""
            SELECT gambling_enabled
              FROM server_settings
             WHERE guild_id = ?
        """, (guild_id,))
        row = await cur.fetchone()
        # default to enabled if no row
        return bool(row[0]) if row else True

    async def set_gambling(self, guild_id: str, enabled: bool):
        """Create or update this guild’s gambling_enabled flag."""
        val = 1 if enabled else 0
        db = await self._db()
        await db.execute("""
          INSERT INTO server_settings(guild_id, gambling_enabled)
          VALUES (?,?)
          ON CONFLICT(guild_id) DO UPDATE SET gambling_enabled=excluded.gambling_enabled;
        """, (guild_id, val))
        await db.commit()
