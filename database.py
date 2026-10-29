import aiosqlite
import json
import asyncio # [NEW]

from datetime import date
from typing import Dict, List, Optional, Any

DB_FILE = "trades.db"

class Database:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file

    async def _execute_with_retry(self, func, *args, **kwargs):
        """Helper to retry DB operations if they are locked."""
        for i in range(3):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if "locked" in str(e).lower() and i < 2:
                    await asyncio.sleep(0.5 * (i + 1))
                    continue
                raise e

    async def init_db(self):
        async with aiosqlite.connect(self.db_file) as db:
            # [HARDENING] Enable WAL mode for concurrency
            await self._execute_with_retry(db.execute, "PRAGMA journal_mode=WAL;")
            
            # Create trades table
            await self._execute_with_retry(db.execute, """
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    time TEXT,
                    symbol TEXT,
                    side TEXT,
                    strategy TEXT,
                    entry_price REAL,
                    qty REAL,
                    used_usd REAL,
                    status TEXT,
                    pnl REAL,
                    sl REAL,
                    tp REAL,
                    exit_price REAL,
                    exit_time TEXT, -- [NEW]
                    current_price REAL,
                    unrealized_pnl REAL,
                    fees_usd REAL,
                    highest_price REAL,
                    trail_active INTEGER, -- Boolean stored as 1/0
                    trail_sl REAL,
                    is_partial INTEGER DEFAULT 0 -- 0=Full, 1=Partial Sold
                )
            """)

            # [MIGRATION] Add is_partial column if not exists
            try:
                await db.execute("ALTER TABLE trades ADD COLUMN is_partial INTEGER DEFAULT 0")
            except Exception:
                pass # Already exists

            # Create users table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    hashed_password TEXT,
                    role TEXT DEFAULT 'viewer',
                    is_active INTEGER DEFAULT 1
                )
            """)

            # Create app_state table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # [NEW] TradingAgents Debate Log Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agent_debates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT,
                    symbol TEXT,
                    strategy TEXT,
                    approved INTEGER,
                    bull_score INTEGER,
                    bear_score INTEGER,
                    bull_thesis TEXT,
                    bear_thesis TEXT,
                    verdict TEXT
                )
            """)

            # [NEW] TradingAgents Post-Trade Reflector Memory Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trade_reflections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT,
                    time TEXT,
                    symbol TEXT,
                    strategy TEXT,
                    outcome TEXT,
                    pnl REAL,
                    pct_move REAL,
                    hold_mins REAL,
                    exit_reason TEXT,
                    lesson TEXT
                )
            """)
            await db.commit()

    # ------------------
    # TRADES
    # ------------------
    async def get_trade(self, trade_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

    async def get_open_trades(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM trades WHERE status = 'open'")
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_all_trades_desc(self, limit=100) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM trades ORDER BY time DESC LIMIT ?", (limit,))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def add_trade(self, trade: Dict[str, Any]):
        keys = list(trade.keys())
        values = list(trade.values())
        placeholders = ",".join(["?"] * len(keys))
        columns = ",".join(keys)
        
        # Convert booleans to int for SQLite
        if 'trail_active' in trade:
            trade['trail_active'] = 1 if trade['trail_active'] else 0
            # Update values list after modification
            values = list(trade.values())

        async with aiosqlite.connect(self.db_file) as db:
            sql = f"INSERT OR REPLACE INTO trades ({columns}) VALUES ({placeholders})"
            await db.execute(sql, values)
            await db.commit()

    async def update_trade(self, trade_id: str, updates: Dict[str, Any]):
        if not updates:
            return

        set_clauses = []
        values = []
        for k, v in updates.items():
            set_clauses.append(f"{k} = ?")
             # Convert booleans to int for SQLite
            if k == 'trail_active':
                v = 1 if v else 0
            values.append(v)
        
        values.append(trade_id)
        sql = f"UPDATE trades SET {', '.join(set_clauses)} WHERE id = ?"

        async with aiosqlite.connect(self.db_file) as db:
            await db.execute(sql, values)
            await db.commit()
            
    async def get_trades_by_strategy(self, strategy: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_file) as db:
             db.row_factory = aiosqlite.Row
             cursor = await db.execute("SELECT * FROM trades WHERE strategy = ?", (strategy,))
             rows = await cursor.fetchall()
             return [dict(r) for r in rows]

    async def get_trades_by_status_symbol_strategy(self, status: str, symbol: str, strategy: str) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trades WHERE status = ? AND symbol = ? AND strategy = ?",
                (status, symbol, strategy)
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ------------------
    # STATE
    # ------------------
    async def get_state(self) -> Dict[str, Any]:
        async with aiosqlite.connect(self.db_file) as db:
            cursor = await db.execute("SELECT key, value FROM app_state")
            rows = await cursor.fetchall()
            state = {}
            for k, v in rows:
                try:
                    state[k] = json.loads(v)
                except:
                    state[k] = v
            return state

    async def set_state_key(self, key: str, value: Any):
        async with aiosqlite.connect(self.db_file) as db:
            val_str = json.dumps(value)
            await self._execute_with_retry(db.execute,
                "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
                (key, val_str)
            )
            await db.commit()

    # ------------------
    # AGENT DEBATES & REFLECTOR MEMORY
    # ------------------
    async def add_agent_debate(self, debate: Dict[str, Any]):
        async with aiosqlite.connect(self.db_file) as db:
            await self._execute_with_retry(
                db.execute,
                """
                INSERT INTO agent_debates
                (time, symbol, strategy, approved, bull_score, bear_score, bull_thesis, bear_thesis, verdict)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    debate.get("time"),
                    debate.get("symbol"),
                    debate.get("strategy"),
                    debate.get("approved", 0),
                    debate.get("bull_score", 0),
                    debate.get("bear_score", 0),
                    debate.get("bull_thesis", ""),
                    debate.get("bear_thesis", ""),
                    debate.get("verdict", ""),
                ),
            )
            await db.commit()

    async def get_recent_debates(self, limit: int = 30) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM agent_debates ORDER BY id DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def add_trade_reflection(self, reflection: Dict[str, Any]):
        async with aiosqlite.connect(self.db_file) as db:
            await self._execute_with_retry(
                db.execute,
                """
                INSERT INTO trade_reflections
                (trade_id, time, symbol, strategy, outcome, pnl, pct_move, hold_mins, exit_reason, lesson)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reflection.get("trade_id"),
                    reflection.get("time"),
                    reflection.get("symbol"),
                    reflection.get("strategy"),
                    reflection.get("outcome"),
                    reflection.get("pnl", 0.0),
                    reflection.get("pct_move", 0.0),
                    reflection.get("hold_mins", 0.0),
                    reflection.get("exit_reason", ""),
                    reflection.get("lesson", ""),
                ),
            )
            await db.commit()

    async def get_reflections_for_symbol(self, symbol: str, limit: int = 5) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trade_reflections WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                (symbol, limit),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_recent_reflections(self, limit: int = 30) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_file) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trade_reflections ORDER BY id DESC LIMIT ?", (limit,)
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

db = Database()
