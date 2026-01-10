
import asyncio
import aiosqlite
import pandas as pd
import ccxt.async_support as ccxt
from datetime import datetime, timezone

from tabulate import tabulate

DB_FILE = "/home/saklain/test_trading_bot/trades.db"

async def run_pattern_analysis():
    # 1. Fetch Losses
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM trades WHERE pnl < 0 ORDER BY time DESC")
        rows = await cursor.fetchall()
        losses = [dict(r) for r in rows]

    if not losses:
        print("No losses to analyze.")
        return

    df = pd.DataFrame(losses)
    
    # 2. Enrich Data
    df['time'] = pd.to_datetime(df['time'])
    df['hour'] = df['time'].dt.hour
    df['symbol_base'] = df['symbol'].apply(lambda x: x.split('/')[0])
    
    # 3. Aggregations
    
    print("\n--- Pattern 1: Strategy Performance ---")
    strat_perf = df.groupby('strategy')['pnl'].agg(['count', 'sum', 'mean']).sort_values('sum')
    print(tabulate(strat_perf, headers='keys', tablefmt='psql'))
    
    print("\n--- Pattern 2: Worst Performing Symbols ---")
    sym_perf = df.groupby('symbol')['pnl'].agg(['count', 'sum']).sort_values('sum').head(10)
    print(tabulate(sym_perf, headers='keys', tablefmt='psql'))
    
    print("\n--- Pattern 3: Hourly Distribution (UTC) ---")
    hour_perf = df.groupby('hour')['pnl'].agg(['count', 'sum']).sort_index()
    # Print simple histogram
    for h, row in hour_perf.iterrows():
        bar = '#' * int(row['count'])
        print(f"{h:02d}:00 | {bar} ({row['count']} losses, sum: ${row['sum']:.2f})")
        
    # 4. BTC Correlation Check
    print("\n--- Pattern 4: BTC Trend Correlation ---")
    # Fetch BTC 1h candles for context
    ex = ccxt.binance()
    try:
        # Get candles covering the range of losses
        min_ts = int(df['time'].min().timestamp() * 1000)
        btc_ohlcv = await ex.fetch_ohlcv("BTC/USDT", "1h", since=min_ts, limit=1000)
        btc_df = pd.DataFrame(btc_ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        btc_df['time'] = pd.to_datetime(btc_df['ts'], unit='ms', utc=True)
        
        # Calculate hourly returns for BTC
        btc_df['btc_return'] = btc_df['close'].pct_change()
        
        # Merge losses with BTC returns (approximate to nearest hour)
        df['hour_ts'] = df['time'].dt.floor('h')
        merged = pd.merge(df, btc_df[['time', 'btc_return']], left_on='hour_ts', right_on='time', how='left')
        
        # Check how many losses happened when BTC was dropping
        btc_dump_losses = merged[merged['btc_return'] < -0.005] # BTC dropped > 0.5% in that hour
        btc_flat_losses = merged[abs(merged['btc_return']) < 0.002]
        btc_pump_losses = merged[merged['btc_return'] > 0.005]
        
        print(f"Losses during BTC Dumps (>0.5% drop/hr): {len(btc_dump_losses)} (Avg Loss: ${btc_dump_losses['pnl'].mean():.2f})")
        print(f"Losses during BTC Pumps (>0.5% gain/hr): {len(btc_pump_losses)} (Avg Loss: ${btc_pump_losses['pnl'].mean():.2f})")
        print(f"Losses during Range/Flat: {len(btc_flat_losses)}")
        
        if len(btc_dump_losses) > len(btc_pump_losses):
            print("👉 PATTERN FOUND: Losses cluster during BTC dumps (System failed to detect Bearish regime fast enough?)")
        else:
            print("👉 No strong correlation with BTC 1h dumps found.")
            
    except Exception as e:
        print(f"Error fetching BTC data: {e}")
    finally:
        await ex.close()

if __name__ == "__main__":
    asyncio.run(run_pattern_analysis())
