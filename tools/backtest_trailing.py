
import asyncio
import aiosqlite
import ccxt.async_support as ccxt
import pandas as pd
from datetime import datetime, timezone
import os
from tabulate import tabulate

DB_FILE = "/home/saklain/test_trading_bot/trades.db"

# Simulation Constants
FIXED_SL_PCT = 0.02   # 2% (Standard)
TRAIL_ACTIVATION = 0.02 # Activate trailing when profit > 2%
TRAIL_DISTANCE = 0.015  # Trail by 1.5%

async def fetch_candles(ex, symbol, start_ts):
    try:
        # Fetch up to 48h of data
        ohlcv = await ex.fetch_ohlcv(symbol, '5m', since=start_ts, limit=576) 
        return ohlcv
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return []

async def run_simulation():
    ex = ccxt.binance()
    
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        # Fetch recent trades
        cursor = await db.execute("SELECT * FROM trades ORDER BY time DESC LIMIT 100")
        rows = await cursor.fetchall()
        trades = [dict(r) for r in rows]

    print(f"Analyzing {len(trades)} trades with Trailing Stop Only (No TP)...")
    
    results = []
    
    for t in trades:
        # Only simulate if we have entry info
        if t['entry_price'] <= 0: continue
        
        sim_result = {
            "symbol": t['symbol'],
            "original_pnl": t['pnl'],
            "new_pnl": 0.0,
            "max_gain_pct": 0.0,
            "outcome": "unknown"
        }
        
        symbol = t['symbol']
        entry_price = t['entry_price']
        entry_time = t['time'].replace('Z', '+00:00')
        
        try:
            dt = datetime.fromisoformat(entry_time)
            start_ts = int(dt.timestamp() * 1000)
        except:
            continue

        candles = await fetch_candles(ex, symbol, start_ts)
        if not candles: continue

        # Simulation Loop
        current_sl = entry_price * (1 - FIXED_SL_PCT)
        trail_active = False
        highest_price = entry_price
        
        exit_price = 0
        exit_reason = "holding"
        
        for c in candles:
            # c = [ts, open, high, low, close, vol]
            high = c[2]
            low = c[3]
            close = c[4]
            
            # 1. Update High Water Mark
            if high > highest_price:
                highest_price = high
                
            # 2. Check Activation
            gain_pct = (highest_price - entry_price) / entry_price
            sim_result['max_gain_pct'] = max(sim_result['max_gain_pct'], gain_pct * 100)
            
            if not trail_active and gain_pct >= TRAIL_ACTIVATION:
                trail_active = True
                # Set initial trail SL
                current_sl = highest_price * (1 - TRAIL_DISTANCE)
            
            # 3. Update Trail if Active
            if trail_active:
                new_trail = highest_price * (1 - TRAIL_DISTANCE)
                if new_trail > current_sl:
                    current_sl = new_trail
            
            # 4. Check Exit (Low hit SL?)
            if low <= current_sl:
                exit_price = current_sl
                # If we gapped through SL, use Open or Low? 
                # Conservative: use SL price. 
                # (Realism: If open < SL, we slipped. But let's assume limit trigger)
                exit_reason = "trail_hit" if trail_active else "sl_hit"
                break
        
        if exit_price == 0:
            # Still open at end of data
            exit_price = candles[-1][4]
            exit_reason = "still_open"

        # Calculate PnL
        trade_qty = t['used_usd'] / entry_price if t['used_usd'] > 0 else (40.0 / entry_price)
        fees = (trade_qty * entry_price * 0.001) + (trade_qty * exit_price * 0.001) # Approx 0.1% each way
        pnl = ((exit_price - entry_price) * trade_qty) - fees
        
        sim_result['new_pnl'] = pnl
        sim_result['outcome'] = exit_reason
        results.append(sim_result)
        
        # Rate limit
        await asyncio.sleep(0.05)

    await ex.close()
    
    # Analysis
    df = pd.DataFrame(results)
    
    total_original = df['original_pnl'].sum()
    total_new = df['new_pnl'].sum()
    
    moonshots = df[df['new_pnl'] > df['original_pnl'] + 1.0] # Gained >$1 more
    given_back = df[df['new_pnl'] < df['original_pnl'] - 1.0] # Lost >$1 compared to original
    
    print("\n" + "="*50)
    print(f"TRAILING STOP RESULTS (No Fixed TP)")
    print("="*50)
    print(f"Original Net PnL (Fixed TP): ${total_original:.2f}")
    print(f"New Net PnL (Trailing Only): ${total_new:.2f}")
    print(f"Difference: ${total_new - total_original:.2f}")
    print("-" * 30)
    print(f"Outperformed Base (Moonshots): {len(moonshots)}")
    print(f"Underperformed Base (Given Back): {len(given_back)}")
    
    if not moonshots.empty:
        print("\n🚀 TOP MOONSHOTS (Caught by Trail):")
        moonshots['improvement'] = moonshots['new_pnl'] - moonshots['original_pnl']
        print(tabulate(moonshots[['symbol', 'original_pnl', 'new_pnl', 'max_gain_pct', 'improvement']].sort_values('improvement', ascending=False).head(10), headers='keys', tablefmt='psql', floatfmt=".2f"))

    if not given_back.empty:
        print("\n📉 TOP FAILURES (Gave Back Profit):")
        given_back['worsening'] = given_back['new_pnl'] - given_back['original_pnl']
        print(tabulate(given_back[['symbol', 'original_pnl', 'new_pnl', 'max_gain_pct', 'worsening']].sort_values('worsening', ascending=True).head(10), headers='keys', tablefmt='psql', floatfmt=".2f"))

if __name__ == "__main__":
    asyncio.run(run_simulation())
