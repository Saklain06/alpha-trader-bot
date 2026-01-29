
import sqlite3
import pandas as pd
import ccxt.base.exchange
import ccxt
import time
from datetime import datetime, timezone, timedelta

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def analyze_pullbacks():
    conn = sqlite3.connect('trades_vps_latest.db')
    df_trades = pd.read_sql_query("SELECT * FROM trades", conn)

    if df_trades.empty:
        print("No trades found.")
        return

    print(f"Analyzing {len(df_trades)} Trades... Fetching history from Binance...")
    
    ex = ccxt.binance()
    
    # Stats
    perfect_pullbacks = []  # High < EMA5
    messy_pullbacks = []    # High >= EMA5 (touched or closed above)
    
    for i, row in df_trades.iterrows():
        try:
            symbol = row['symbol']
            entry_time_str = row['time'] # ISO Format
            
            # Parse time
            try:
                dt_entry = datetime.fromisoformat(entry_time_str)
            except:
                dt_entry = datetime.strptime(entry_time_str, "%Y-%m-%dT%H:%M:%S.%f") # Manual Fallback
            
            # Timestamp (ms)
            ts_entry = int(dt_entry.timestamp() * 1000)
            
            # Fetch OHLCV surrounding this time
            # We need at least 50 candles BEFORE to calc EMA
            # Start fetching ~24 hours before
            since = ts_entry - (24 * 60 * 60 * 1000)
            
            # Fetch
            ohlcv = ex.fetch_ohlcv(symbol, '15m', since=since, limit=100)
            if not ohlcv: continue
            
            df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            df['ema5'] = calculate_ema(df['close'], 5)
            
            # Find the candle corresponding to Entry Time
            # We look for the candle where 'ts' <= entry_ts < 'ts + 15m'
            # ACTUALLY, the bot enters on the CLOSE of the "Reclaim Candle".
            # So the Entry Time should match the OPEN time of the *next* candle (the trade candle).
            # We want to analyze the candle BEFORE the Entry Trigger.
            
            # Let's find the index closest to entry time
            # The trade `time` is when the bot executed.
            # If the bot executes on candle close, the trade time is roughly Candle_Open + 15m.
            
            # Locate the candle index
            match_idx = -1
            for idx, c_row in df.iterrows():
                # If candle starts within 15 mins of trade time, this is the "Current" candle
                if abs(c_row['ts'] - ts_entry) < (15 * 60 * 1000): 
                     match_idx = idx
                     break
            
            if match_idx < 2: continue # Need history
            
            # Logic:
            # Trade triggers on specific conditions.
            # We assume Entry was on Candle `match_idx`.
            # Reclaim Candle = `match_idx - 1`.
            # Pullback Candle = `match_idx - 2` (The one that went below EMA).
            
            # Wait, the strategy is:
            # 1. Prev Candle closed BELOW EMA5. (Pullback)
            # 2. Curr Candle closed ABOVE EMA5. (Reclaim)
            # 3. Enter on NEXT Open.
            
            # So:
            # Entry Candle = `match_idx` (Just opened).
            # Reclaim Candle = `match_idx - 1`.
            # Pullback Candle = `match_idx - 2`.
            
            reclaim_c = df.iloc[match_idx - 1]
            pullback_c = df.iloc[match_idx - 2]
            
            ema5_pullback = pullback_c['ema5']
            high_pullback = pullback_c['high']
            
            # CHECK: Was Pullback Candle FULLY BELOW EMA5?
            # i.e. High < EMA5
            is_perfect = high_pullback < ema5_pullback
            
            info = {
                'symbol': symbol,
                'pnl': float(row['pnl']),
                'fees': float(row['fees_usd']),
                'status': row['status']
            }
            
            if is_perfect:
                perfect_pullbacks.append(info)
            else:
                messy_pullbacks.append(info)
                
            time.sleep(0.1) # Respect rate limits
            
        except Exception as e:
            # print(f"Error {row['symbol']}: {e}")
            continue

    # Analysis
    def calc_stats(lst, name):
        if not lst:
            print(f"No trades found for {name}")
            return
            
        total = len(lst)
        wins = len([x for x in lst if x['pnl'] > 0])
        total_pnl = sum([x['pnl'] for x in lst])
        total_fees = sum([x['fees'] for x in lst])
        net_pnl = total_pnl - total_fees # Assuming PnL in DB includes fees? Wait, let's reuse previous logic.
        # DB 'pnl' usually NET.
        
        print(f"--- {name} ({total} Trades) ---")
        print(f"Win Rate: {(wins/total*100):.1f}%")
        print(f"Total PnL (DB): ${total_pnl:.2f}")
        print(f"Avg PnL: ${(total_pnl/total):.2f}")

    print("\n" + "="*40)
    print("🔬 FORENSIC ANALYSIS: EMA-5 PULLBACK QUALITY")
    print("Condition: Pullback Candle High < EMA-5 (No Touch)")
    print("="*40 + "\n")
    
    calc_stats(perfect_pullbacks, "✅ PERFECT PULLBACKS (Fully Below)")
    calc_stats(messy_pullbacks, "⚠️ MESSY PULLBACKS (Touched Line)")

if __name__ == "__main__":
    analyze_pullbacks()
