
import asyncio
import aiosqlite

async def fix_records():
    print("--- FIXING DB RECORDS ---")
    async with aiosqlite.connect("trades.db") as db:
        # 1. Fix Timezones (Append Z if missing)
        # 13:36:51 -> 13:36:51Z
        # We target specific recently closed trades
        await db.execute("""
            UPDATE trades 
            SET exit_time = exit_time || 'Z'
            WHERE status='closed' 
            AND exit_time IS NOT NULL 
            AND exit_time NOT LIKE '%Z' 
            AND exit_time NOT LIKE '%+%'
        """)
        
        # 2. Fix Zero Used USD (Set to 10.0 default so Qty shows up)
        # Only for Closed trades where UsedUSD is 0
        await db.execute("""
            UPDATE trades 
            SET used_usd = 10.0
            WHERE status='closed' AND used_usd = 0
        """)
        
        await db.commit()
        print("✅ Fixed Timezones and UsedUSD.")

if __name__ == "__main__":
    asyncio.run(fix_records())
