
import sqlite3
import pandas as pd
import json

DB_FILE = "/opt/gitco/alpha-trader-bot/trades.db"

try:
    conn = sqlite3.connect(DB_FILE)
    query = "SELECT symbol, entry_price, exit_price, pnl, time, exit_time FROM trades WHERE status='closed' ORDER BY time DESC LIMIT 60"
    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        print("No closed trades found.")
        exit()

    # Metrics
    total_trades = len(df)
    wins = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    
    win_rate = (len(wins) / total_trades) * 100
    total_pnl = df['pnl'].sum()
    avg_win = wins['pnl'].mean() if not wins.empty else 0
    avg_loss = losses['pnl'].mean() if not losses.empty else 0
    
    # Duration Analysis
    df['entry_dt'] = pd.to_datetime(df['time'])
    df['exit_dt'] = pd.to_datetime(df['exit_time'])
    df['duration'] = (df['exit_dt'] - df['entry_dt']).dt.total_seconds() / 60 # Minutes
    
    avg_duration = df['duration'].mean()
    win_duration = df[df['pnl'] > 0]['duration'].mean()
    loss_duration = df[df['pnl'] <= 0]['duration'].mean()

    print(f"--- ANALYSIS (Last {total_trades} Trades) ---")
    print(f"Total PnL: ${total_pnl:.2f}")
    print(f"Win Rate:  {win_rate:.1f}% ({len(wins)} W / {len(losses)} L)")
    print(f"Avg Win:   ${avg_win:.2f}")
    print(f"Avg Loss:  ${avg_loss:.2f}")
    print(f"Risk/Reward Realized: {abs(avg_win/avg_loss):.2f} (Target was 2.0)")
    print(f"")
    print(f"--- TIMING ---")
    print(f"Avg Hold Time: {avg_duration:.1f} min")
    print(f"Avg Win Hold:  {win_duration:.1f} min")
    print(f"Avg Loss Hold: {loss_duration:.1f} min")
    print(f"")
    print(f"--- WORST OFFENDERS ---")
    print(losses.sort_values('pnl').head(5)[['symbol', 'pnl', 'duration']].to_string(index=False))

except Exception as e:
    print(f"Error: {e}")
