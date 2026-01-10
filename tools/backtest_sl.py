
import asyncio
import aiosqlite
import ccxt.async_support as ccxt
import pandas as pd
from datetime import datetime, timezone
import os
from tabulate import tabulate

DB_FILE = "/home/saklain/test_trading_bot/trades.db"

# Simulation Constants
NEW_SL_PCT = 0.04  # 4%
TP_PCT = 0.06      # 6% (Assuming original target)
MAX_HOLD_HOURS = 48 # Don't look further than 2 days

async def fetch_candles(ex, symbol, start_ts):
    # Fetch enough 5m candles to cover 48 hours (~576 candles)
    # limit=1000 is safe
    try:
        ohlcv = await ex.fetch_ohlcv(symbol, '5m', since=start_ts, limit=1000)
        return ohlcv
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return []

async def run_simulation():
    # 1. Setup Exchange
    ex = ccxt.binance()
    
    # 2. Get Trades
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM trades ORDER BY time DESC LIMIT 100")
        rows = await cursor.fetchall()
        trades = [dict(r) for r in rows]

    print(f"Analyzing {len(trades)} trades...")
    
    results = []
    
    for t in trades:
        # We only care about LOSSES that might have been saved.
        # If it was a WIN, we assume 4% SL wouldn't hurt it (unless it dipped -3% before winning? We skip that complexity for now)
        # Actually, let's only strictly simulate the LOSSES.
        # "Status: Closed" and "PnL < 0"
        
        sim_result = {
            "symbol": t['symbol'],
            "original_pnl": t['pnl'],
            "original_status": "loss" if t['pnl'] < 0 else "win",
            "new_pnl": t['pnl'], # Default to same
            "outcome": "same"
        }
        
        if t['pnl'] < 0 and t['entry_price'] > 0:
            symbol = t['symbol']
            entry_price = t['entry_price']
            entry_time = t['time'].replace('Z', '+00:00')
            try:
                dt = datetime.fromisoformat(entry_time)
                start_ts = int(dt.timestamp() * 1000)
            except:
                continue

            # Fetch history
            candles = await fetch_candles(ex, symbol, start_ts)
            
            # Simulate
            sl_price = entry_price * (1 - NEW_SL_PCT)
            tp_price = entry_price * (1 + TP_PCT)
            
            hit_new_sl = False
            hit_tp = False
            exit_price = 0
            
            for c in candles:
                # c = [ts, open, high, low, close, vol]
                low = c[3]
                high = c[2]
                close = c[4]
                
                # Check SL first (conservative)
                if low <= sl_price:
                    hit_new_sl = True
                    exit_price = sl_price
                    break
                
                # Check TP
                if high >= tp_price:
                    hit_tp = True
                    exit_price = tp_price
                    break
            
            # Determine Result
            trade_value = t['used_usd'] # Approx trade size
            
            if hit_tp:
                pnl = (tp_price - entry_price) * (trade_value / entry_price)
                sim_result['new_pnl'] = pnl
                sim_result['outcome'] = "recovered"
            elif hit_new_sl:
                pnl = (sl_price - entry_price) * (trade_value / entry_price)
                sim_result['new_pnl'] = pnl
                sim_result['outcome'] = "worsened" # 4% loss is worse than 2%
            else:
                # Still Open (or ran out of data)
                # Mark as unrealized PnL at last close
                if candles:
                    last_close = candles[-1][4]
                    pnl = (last_close - entry_price) * (trade_value / entry_price)
                    sim_result['new_pnl'] = pnl
                    sim_result['outcome'] = "open/holding"
        
        results.append(sim_result)
        # Rate limit
        await asyncio.sleep(0.1)

    await ex.close()
    
    # Aggregation
    df = pd.DataFrame(results)
    
    total_original = df['original_pnl'].sum()
    total_new = df['new_pnl'].sum()
    
    recovered = df[df['outcome'] == 'recovered']
    worsened = df[df['outcome'] == 'worsened']
    holding = df[df['outcome'] == 'open/holding']
    
    print("\n" + "="*50)
    print(f"WHAT-IF RESULTS (SL=4%, TP=6%)")
    print("="*50)
    print(f"Original Net PnL: ${total_original:.2f}")
    print(f"New Projected PnL: ${total_new:.2f}")
    print(f"Difference: ${total_new - total_original:.2f}")
    print("-" * 30)
    print(f"Trades Recovered (Loss -> Win): {len(recovered)}")
    print(f"Trades Worsened (2% Loss -> 4% Loss): {len(worsened)}")
    print(f"Trades Still Holding: {len(holding)}")
    
    if not recovered.empty:
        print("\nTop Recoveries:")
        print(tabulate(recovered[['symbol', 'original_pnl', 'new_pnl']].head(10), headers='keys', tablefmt='psql'))
        
    if not worsened.empty:
        print("\nTop Worsened (Bigger Losses):")
        print(tabulate(worsened[['symbol', 'original_pnl', 'new_pnl']].head(10), headers='keys', tablefmt='psql'))

if __name__ == "__main__":
    asyncio.run(run_simulation())
