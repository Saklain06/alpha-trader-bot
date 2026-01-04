import aiosqlite
import json
import logging
from datetime import date
from typing import Dict, List, Optional, Any

DB_FILE = "trades.db"

class Database:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file

    async def init_db(self):
        async with aiosqlite.connect(self.db_file) as db:
            # [HARDENING] Enable WAL mode for concurrency
            await db.execute("PRAGMA journal_mode=WAL;")
            
            # Create trades table
            await db.execute("""
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
                    current_price REAL,
                    unrealized_pnl REAL,
                    fees_usd REAL,
                    highest_price REAL,
                    trail_active INTEGER, -- Boolean stored as 1/0
                    trail_sl REAL
                )
            """)

            # Create app_state table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
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
            await db.execute(
                "INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)",
                (key, val_str)
            )
            await db.commit()

db = Database()
