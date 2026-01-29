
import sqlite3
import pandas as pd
from datetime import datetime

def analyze():
    # [FIX] Analyze the FRESH database downloaded from VPS
    conn = sqlite3.connect('trades_new.db')
    
    # Load ALL trades
    query = "SELECT * FROM trades"
    df = pd.read_sql_query(query, conn)
    
    if df.empty:
        print("No trades found.")
        return

    # Convert numeric columns
    numeric_cols = ['pnl', 'used_usd', 'entry_price', 'exit_price', 'fees_usd', 'unrealized_pnl', 'qty']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    # Filter by Status
    closed_trades = df[df['status'] == 'closed']
    open_trades = df[df['status'] == 'open']
    
    total_count = len(df)
    closed_count = len(closed_trades)
    open_count = len(open_trades)

    # Calculate PnL
    realized_pnl = closed_trades['pnl'].sum()
    est_unrealized_pnl = open_trades['unrealized_pnl'].sum()
    total_fees = df['fees_usd'].sum()
    
    # Net PnL (assuming 'pnl' in DB is usually Gross, checks required)
    # If pnl column is Net, then realized_pnl is fine. 
    # Usually bots store Gross PnL in 'pnl' and fees separately. 
    # Let's calculate both.
    
    net_realized_pnl = realized_pnl  # Assuming DB stores Net, but let's check
    # If user sees -0.42, maybe fees are the difference?
    
    # Win/Loss on Closed
    wins = closed_trades[closed_trades['pnl'] > 0]
    losses = closed_trades[closed_trades['pnl'] <= 0]
    
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / closed_count * 100) if closed_count > 0 else 0

    print(f"--- 📊 DETAILED RECONCILIATION ({total_count} Total Trades) ---")
    print(f"Status Breakdown: {closed_count} Closed, {open_count} Open")
    print(f"----------------------------------------")
    print(f"Realized PnL (Closed):   ${realized_pnl:.2f}")
    print(f"Unrealized PnL (Open):   ${est_unrealized_pnl:.2f}")
    print(f"Total Fees Paid:         ${total_fees:.2f}")
    print(f"----------------------------------------")
    print(f"Net PnL (Realized - Fees?): ${realized_pnl - total_fees:.2f} (If fees not included)")
    print(f"Total Portfolio Impact:     ${realized_pnl + est_unrealized_pnl:.2f}")
    print(f"----------------------------------------")
    
    if open_count > 0:
        print("\nOpen Positions:")
        print(open_trades[['symbol', 'entry_price', 'unrealized_pnl']].to_string(index=False))

if __name__ == "__main__":
    analyze()
