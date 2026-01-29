
import sqlite3
import pandas as pd

def check_slots():
    conn = sqlite3.connect('trades.db')
    
    print("--- Last 10 Trades in DB ---")
    query_all = "SELECT id, symbol, time, status, exit_time FROM trades ORDER BY time DESC LIMIT 10"
    df_all = pd.read_sql_query(query_all, conn)
    
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    print(df_all)

if __name__ == "__main__":
    check_slots()
