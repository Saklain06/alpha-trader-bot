import asyncio
import aiosqlite
import pandas as pd
from tabulate import tabulate

DB_FILE = "/home/saklain/test_trading_bot/trades.db"

async def analyze_trades():
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        # Fetch last 90 trades ordered by time desc
        cursor = await db.execute("SELECT * FROM trades ORDER BY time DESC LIMIT 90")
        rows = await cursor.fetchall()
        trades = [dict(r) for r in rows]

    if not trades:
        print("No trades found.")
        return

    # Convert to DataFrame for easier analysis
    df = pd.DataFrame(trades)
    
    # Ensure numeric columns are floats
    numeric_cols = ['pnl', 'used_usd', 'entry_price', 'exit_price', 'fees_usd']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    # Filter for closed trades for PnL analysis
    closed_trades = df[df['status'] == 'closed']
    
    print(f"Total Trades Fetched: {len(df)}")
    print(f"Closed Trades: {len(closed_trades)}")
    print(f"Open Trades: {len(df) - len(closed_trades)}")
    print("-" * 40)

    if not closed_trades.empty:
        total_pnl = closed_trades['pnl'].sum()
        total_fees = closed_trades['fees_usd'].sum()
        net_pnl = total_pnl - total_fees
        
        wins = closed_trades[closed_trades['pnl'] > 0]
        losses = closed_trades[closed_trades['pnl'] <= 0]
        
        win_rate = (len(wins) / len(closed_trades)) * 100 if len(closed_trades) > 0 else 0
        avg_win = wins['pnl'].mean() if not wins.empty else 0
        avg_loss = losses['pnl'].mean() if not losses.empty else 0
        
        print("Performance Analysis (Last 90 Trades):")
        print(f"Total PnL (Gross): ${total_pnl:.2f}")
        print(f"Total Fees: ${total_fees:.2f}")
        print(f"Net PnL: ${net_pnl:.2f}")
        print(f"Win Rate: {win_rate:.2f}%")
        print(f"Avg Win: ${avg_win:.2f}")
        print(f"Avg Loss: ${avg_loss:.2f}")
        
    print("-" * 40)
    print("Recent 10 Trades:")
    # Select relevant columns for display
    display_cols = ['time', 'symbol', 'side', 'strategy', 'status', 'pnl', 'used_usd']
    print(tabulate(df[display_cols].head(10), headers='keys', tablefmt='psql'))

if __name__ == "__main__":
    asyncio.run(analyze_trades())
