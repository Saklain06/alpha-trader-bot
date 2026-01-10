import asyncio
import aiosqlite
import pandas as pd
from tabulate import tabulate
from datetime import datetime

DB_FILE = "/home/saklain/test_trading_bot/trades.db"

async def analyze_losses():
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        # Fetch all closed trades
        cursor = await db.execute("SELECT * FROM trades WHERE status = 'closed' ORDER BY pnl ASC")
        rows = await cursor.fetchall()
        trades = [dict(r) for r in rows]

    if not trades:
        print("No closed trades found.")
        return

    df = pd.DataFrame(trades)
    
    # numeric conversion
    cols = ['pnl', 'entry_price', 'exit_price', 'qty', 'used_usd', 'fees_usd', 'sl']
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)

    # Filter for losses
    loss_df = df[df['pnl'] < 0].copy()
    
    if loss_df.empty:
        print("No losses found! (Great job?)")
        return

    # Calculate Loss Percentage
    loss_df['loss_pct'] = (loss_df['pnl'] / loss_df['used_usd']) * 100
    
    # Calculate Duration
    def calc_duration(row):
        try:
            start = datetime.fromisoformat(row['time'].replace('Z', '+00:00'))
            if row.get('exit_time'):
                end = datetime.fromisoformat(row['exit_time'].replace('Z', '+00:00'))
                return (end - start).total_seconds() / 60 # minutes
            return 0
        except:
            return 0
            
    loss_df['duration_min'] = loss_df.apply(calc_duration, axis=1)

    # Define "Big Loss" as bottom 20% of PnL OR loss > $1.0 (arbitrary, based on $40 trade size usually 2.5%)
    # Let's look at worst 10
    worst_losses = loss_df.sort_values('pnl', ascending=True).head(15)

    print(f"\nTotal Losses: {len(loss_df)}")
    print(f"Avg Loss Amount: ${loss_df['pnl'].mean():.2f}")
    print(f"Avg Loss Pct: {loss_df['loss_pct'].mean():.2f}%")
    print("-" * 60)
    print("TOP 15 WORST LOSSES:")
    
    display_cols = ['time', 'symbol', 'strategy', 'pnl', 'loss_pct', 'duration_min', 'sl', 'exit_price']
    print(tabulate(worst_losses[display_cols], headers='keys', tablefmt='psql', floatfmt=".2f"))

    print("\n--- Analysis of Worst Losses ---")
    
    # Check for Slippage (Exit Price vs SL)
    # If SL > 0 and Exit Price << SL, then slippage occurred
    worst_losses['slippage_pct'] = 0.0
    for idx, row in worst_losses.iterrows():
        if row['sl'] > 0:
            # For LONG, SL is below entry. If exit is below SL, that's slippage.
            # slippage = (SL - Exit) / SL
            if row['exit_price'] < row['sl']:
                slip = (row['sl'] - row['exit_price']) / row['sl'] * 100
                worst_losses.at[idx, 'slippage_pct'] = slip

    slippage_victims = worst_losses[worst_losses['slippage_pct'] > 0.1] # Ignore tiny diffs
    if not slippage_victims.empty:
        print(f"\n⚠️ SLIPPAGE DETECTED on {len(slippage_victims)} trades (Exit < SL):")
        print(tabulate(slippage_victims[['symbol', 'pnl', 'sl', 'exit_price', 'slippage_pct']], headers='keys', tablefmt='psql', floatfmt=".4f"))
    else:
        print("\n✅ No significant slippage detected (Exits roughly respected SL).")

    # Time Held Analysis
    print("\nDuration Stats for Losers:")
    print(loss_df['duration_min'].describe())

if __name__ == "__main__":
    asyncio.run(analyze_losses())
