import aiosqlite
import asyncio

DB_FILE = "trades.db"

async def migrate():
    print("🔄 Migrating Database...")
    async with aiosqlite.connect(DB_FILE) as db:
        try:
            await db.execute("ALTER TABLE trades ADD COLUMN exit_time TEXT")
            print("✅ Added 'exit_time' column.")
        except Exception as e:
            if "duplicate column" in str(e):
                print("ℹ️ 'exit_time' column already exists.")
            else:
                print(f"⚠️ Error adding column: {e}")
        
        await db.commit()
    print("✅ Migration Complete.")

if __name__ == "__main__":
    asyncio.run(migrate())
