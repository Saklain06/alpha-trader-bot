
import asyncio
import aiosqlite
import pytz
from datetime import datetime

async def inspect_trades():
    print("--- INSPECTING TRADES ---")
    async with aiosqlite.connect("trades.db") as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM trades WHERE symbol IN ('VELODROME/USDT', 'DOGE/USDT', 'WAL/USDT', 'WIF/USDT') ORDER BY time DESC")
        rows = await cursor.fetchall()

        for row in rows:
            t = dict(row)
            print(f"\nSymbol: {t['symbol']}")
            print(f"Status: {t['status']}")
            print(f"Raw Time (Entry): {t['time']}")
            print(f"Raw Exit Time:    {t['exit_time']}")
            print(f"Qty:      {t['qty']}")
            print(f"Used USD: {t['used_usd']}")
            print(f"Entry $:  {t['entry_price']}")

if __name__ == "__main__":
    asyncio.run(inspect_trades())
