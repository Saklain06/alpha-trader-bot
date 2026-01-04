
import asyncio
import aiosqlite
from datetime import datetime
import pytz

async def check_data_trade():
    async with aiosqlite.connect("trades.db") as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM trades WHERE symbol LIKE 'DATA/%' ORDER BY time DESC LIMIT 1")
        row = await cursor.fetchone()
        
        if row:
            t = dict(row)
            # Time Conversion
            utc = pytz.utc
            ist = pytz.timezone('Asia/Kolkata')
            
            entry_time = datetime.fromisoformat(t['time'].replace('Z', '+00:00')).astimezone(ist)
            exit_time = datetime.fromisoformat(t['exit_time'].replace('Z', '+00:00')).astimezone(ist) if t['exit_time'] else None
            
            # Qty Recalc
            calc_qty = t['used_usd'] / t['entry_price'] if t['entry_price'] else 0
            
            print(f"Symbol: {t['symbol']}")
            print(f"Entry Time (IST): {entry_time.strftime('%Y-%m-%d %I:%M:%S %p')}")
            print(f"Exit Time (IST):  {exit_time.strftime('%Y-%m-%d %I:%M:%S %p') if exit_time else 'N/A'}")
            print(f"Original Qty:     {calc_qty:.4f}")
            print(f"Used USD:         ${t['used_usd']:.2f}")

if __name__ == "__main__":
    asyncio.run(check_data_trade())
