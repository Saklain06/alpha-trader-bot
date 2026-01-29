from database import Database
from auth import get_password_hash
import asyncio

async def seed():
    print("🌱 Seeding Admin User...")
    db = Database()
    
    # Change this default password immediately after login!
    default_user = "admin"
    default_pass = "admin123"
    hashed = get_password_hash(default_pass)
    
    await db.init_db() # Ensure table exists
    
    await db.init_db() # Ensure table exists
    
    # Direct DB access for seeding

    import aiosqlite
    async with aiosqlite.connect("trades.db") as conn:
        try:
             await conn.execute("INSERT INTO users (username, hashed_password, role) VALUES (?, ?, ?)", 
                                (default_user, hashed, "admin"))
             await conn.commit()
             print(f"✅ Created user: {default_user} / {default_pass}")
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                 print("ℹ️ User already exists.")
            else:
                 print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(seed())
