import asyncio
import aiosqlite
import sys
from auth import get_password_hash

async def change_password(username, new_password):
    db_file = "trades.db"
    hashed_pw = get_password_hash(new_password)
    
    async with aiosqlite.connect(db_file) as db:
        await db.execute(
            "UPDATE users SET hashed_password = ? WHERE username = ?",
            (hashed_pw, username)
        )
        await db.commit()
        print(f"✅ Password for user '{username}' updated successfully.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 change_password.py <new_password>")
        new_pass = input("Enter new password: ").strip()
    else:
        new_pass = sys.argv[1]

    if new_pass:
        asyncio.run(change_password("admin", new_pass))
    else:
        print("❌ Password cannot be empty.")
