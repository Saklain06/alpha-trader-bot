
import sqlite3
import pandas as pd

def check_live_trades():
    conn = sqlite3.connect('trades_vps_check.db')
    
    print("--- Active Trades (VPS) ---")
    query = "SELECT id, symbol, time, entry_price, status FROM trades WHERE status='open' ORDER BY time DESC"
    df = pd.read_sql_query(query, conn)
    
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(df)
    
    # Also check recently closed just in case
    print("\n--- Recently Closed (Last 5) ---")
    query_closed = "SELECT id, symbol, time, entry_price, exit_price, pnl, status FROM trades WHERE status='closed' ORDER BY time DESC LIMIT 5"
    df_closed = pd.read_sql_query(query_closed, conn)
    print(df_closed)

if __name__ == "__main__":
    check_live_trades()
