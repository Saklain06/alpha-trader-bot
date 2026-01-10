
import asyncio
import aiosqlite
import ccxt.async_support as ccxt
import pandas as pd
from datetime import datetime
from tabulate import tabulate

DB_FILE = "/home/saklain/test_trading_bot/trades.db"
TPS_TO_TEST = [0.06, 0.07, 0.08]
FIXED_SL_PCT = 0.02

async def fetch_candles(ex, symbol, start_ts):
    try:
        # Fetch 48h (approx 576 5m candles)
        ohlcv = await ex.fetch_ohlcv(symbol, '5m', since=start_ts, limit=1000)
        return ohlcv
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return []

async def run_simulation():
    ex = ccxt.binance()
    
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        # Fetch valid trades
        cursor = await db.execute("SELECT * FROM trades WHERE entry_price > 0 ORDER BY time DESC LIMIT 100")
        rows = await cursor.fetchall()
        trades = [dict(r) for r in rows]

    print(f"analyzing {len(trades)} trades across TPs: {[x*100 for x in TPS_TO_TEST]}%...")
    
    results = {tp: [] for tp in TPS_TO_TEST}
    
    count = 0
    for t in trades:
        symbol = t['symbol']
        entry_price = t['entry_price']
        trade_usd = t['used_usd'] if t['used_usd'] > 0 else 40.0
        
        try:
            entry_time = t['time'].replace('Z', '+00:00')
            dt = datetime.fromisoformat(entry_time)
            start_ts = int(dt.timestamp() * 1000)
        except:
            continue

        candles = await fetch_candles(ex, symbol, start_ts)
        if not candles: continue

        # Run Sim for each TP on SAME candles
        for tp_pct in TPS_TO_TEST:
            sl_price = entry_price * (1 - FIXED_SL_PCT)
            tp_price = entry_price * (1 + tp_pct)
            
            pnl = 0.0
            outcome = "open"
            
            for c in candles:
                low = c[3]
                high = c[2]
                close = c[4]
                
                # Check SL first
                if low <= sl_price:
                    pnl = (sl_price - entry_price) * (trade_usd / entry_price)
                    outcome = "loss"
                    break
                
                # Check TP
                if high >= tp_price:
                    pnl = (tp_price - entry_price) * (trade_usd / entry_price)
                    outcome = "win"
                    break
            
            if outcome == "open":
                # Mark to market
                last_close = candles[-1][4]
                pnl = (last_close - entry_price) * (trade_usd / entry_price)
            
            # Deduct fees (approx)
            fees = trade_usd * 0.002 # 0.1% entry + 0.1% exit
            pnl -= fees
            
            results[tp_pct].append({"symbol": symbol, "pnl": pnl, "outcome": outcome})
        
        count += 1
        if count % 10 == 0:
            print(f"Processed {count} trades...")
        await asyncio.sleep(0.05)

    await ex.close()
    
    print("\n" + "="*60)
    print(f"TP VARIATION RESULTS (SL Fixed @ 2%)")
    print("="*60)
    
    summary = []
    best_pnl = -99999
    best_tp = 0
    
    for tp_pct in TPS_TO_TEST:
        data = results[tp_pct]
        df = pd.DataFrame(data)
        total_pnl = df['pnl'].sum()
        wins = len(df[df['outcome'] == 'win'])
        losses = len(df[df['outcome'] == 'loss'])
        win_rate = (wins / len(df)) * 100 if len(df) > 0 else 0
        
        summary.append([f"{tp_pct*100}%", f"${total_pnl:.2f}", wins, losses, f"{win_rate:.1f}%"])
        
        if total_pnl > best_pnl:
            best_pnl = total_pnl
            best_tp = tp_pct

    print(tabulate(summary, headers=["TP Target", "Net PnL", "Wins", "Losses", "Win Rate"], tablefmt="psql"))

if __name__ == "__main__":
    asyncio.run(run_simulation())
