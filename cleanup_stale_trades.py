
import sqlite3
from datetime import datetime, timedelta

def cleanup_stale_trades():
    db_path = 'trades.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cutoff_time = datetime.now() - timedelta(days=1)
    cutoff_str = cutoff_time.isoformat()
    
    print(f"Cleaning open trades older than {cutoff_str}...")
    
    # Check count first
    cursor.execute("SELECT count(*) FROM trades WHERE status='open' AND time < ?", (cutoff_str,))
    count = cursor.fetchone()[0]
    print(f"Found {count} stale open trades.")
    
    if count > 0:
        cursor.execute("SELECT symbol, time FROM trades WHERE status='open' AND time < ?", (cutoff_str,))
        rows = cursor.fetchall()
        for r in rows:
            print(f" -> Deleting stale trade: {r[0]} (Entry: {r[1]})")
        
        # Delete them
        cursor.execute("DELETE FROM trades WHERE status='open' AND time < ?", (cutoff_str,))
        conn.commit()
        print(">> Stale trades deleted. Slots should be free.")
    else:
        print(">> No stale trades found.")
    
    conn.close()

if __name__ == "__main__":
    cleanup_stale_trades()
