
import asyncio
import aiosqlite
from datetime import datetime, timedelta, timezone
from tabulate import tabulate

DB_FILE = "/home/saklain/test_trading_bot/trades.db"

async def check_recent_activity():
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        
        # Calculate 24h ago
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        
        cursor = await db.execute("SELECT * FROM trades WHERE time > ? ORDER BY time DESC", (since,))
        rows = await cursor.fetchall()
        trades = [dict(r) for r in rows]
        
        # Also check state
        cursor = await db.execute("SELECT * FROM app_state")
        state_rows = await cursor.fetchall()
        state = {r['key']: r['value'] for r in state_rows}

    print(f"\nTime Now (UTC): {datetime.now(timezone.utc).isoformat()}")
    print("-" * 50)
    print(f"State Summary:")
    print(f"Auto Trading: {state.get('auto_trading')}")
    print(f"Kill Switch: {state.get('kill_switch')}")
    print(f"Trades Today: {state.get('trades_today')}")
    print("-" * 50)
    
    if not trades:
        print("No trades in the last 24 hours.")
    else:
        print(f"Trades in last 24h: {len(trades)}")
        cols = ['time', 'symbol', 'side', 'strategy', 'status', 'pnl', 'entry_price', 'exit_price']
        print(tabulate(trades, headers='keys', tablefmt='psql'))

if __name__ == "__main__":
    asyncio.run(check_recent_activity())
