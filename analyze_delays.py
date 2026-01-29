
import ccxt
import pandas as pd
from datetime import datetime

def analyze_delays():
    ex = ccxt.binance()
    
    # 1. JST Analysis
    # Entry: 16:43:56. Signal should be 16:30:00 (Open).
    # Reclaim Candle: 16:15. Pullback: 16:00.
    analyze_trade(ex, "JST/USDT", "2026-01-26 16:43:56", "2026-01-26 16:30:00", "2026-01-26 16:15:00")

    # 2. FOGO Analysis (Assuming FOGO is FOGO lol, or I search for it)
    # Entry: 09:33:48. Signal should be 09:30:00.
    # Reclaim Candle: 09:15.
    analyze_trade(ex, "FOGO/USDT", "2026-01-26 09:33:48", "2026-01-26 09:30:00", "2026-01-26 09:15:00")

def analyze_trade(ex, symbol, entry_time_str, signal_time_str, reclaim_time_str):
    print(f"\nBS================ {symbol} ================")
    print(f"Entry Time: {entry_time_str}")
    
    # Fetch Data around signal time
    ts_entry = int(pd.Timestamp(entry_time_str).timestamp() * 1000)
    ohlcv = ex.fetch_ohlcv(symbol, '15m', limit=50, params={'endTime': ts_entry + 900000}) # Get context including entry
    df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
    df['date'] = pd.to_datetime(df['ts'], unit='ms')
    
    # Identify Reclaim Candle
    reclaim_target = pd.Timestamp(reclaim_time_str)
    reclaim = df[df['date'] == reclaim_target]
    
    entry_price = 0.04696 if "JST" in symbol else 0.03784 
    # Hardcoded from earlier DB check for speed
    
    if not reclaim.empty:
        r_close = reclaim.iloc[0]['close']
        r_high = reclaim.iloc[0]['high']
        print(f"Reclaim Candle ({reclaim_time_str}): Close {r_close} | High {r_high}")
        
        # Calculate Slippage
        slip_close = (entry_price - r_close) / r_close * 100
        print(f"Entry Price: {entry_price}")
        print(f"⚠️ Deviation from Reclaim Close: +{slip_close:.2f}%")
        
        if slip_close > 1.0:
            print(">> CONFIRMED: High deviation/slippage due to late entry.")
    else:
        print("Reclaim candle not found in history.")

    # Check 1H Trend Context at Signal Time (Why was it late?)
    # Signal Time: 16:30 for JST.
    # 1H Trend Check uses 1H candles.
    # At 16:30, the "Live" 1H candle is 16:00-17:00.
    # The "Closed" 1H candle is 15:00-16:00.
    
    print("Fetching 1H Data for Trend Check...")
    ohlcv_1h = ex.fetch_ohlcv(symbol, '1h', limit=20, params={'endTime': ts_entry + 3600000})
    df_1h = pd.DataFrame(ohlcv_1h, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
    df_1h['date'] = pd.to_datetime(df_1h['ts'], unit='ms')
    df_1h['ema50'] = df_1h['close'].ewm(span=50, adjust=False).mean()
    
    # Check the 1H candle that was LIVE at entry (JST 16:43 -> 16:00 candle)
    # Check the 1H candle that was CLOSED (JST 16:30 -> 15:00 candle)
    
    # For JST (16:43):
    # Live Candle 16:00. Open 16:00.
    # Closed Candle 15:00.
    
    # For FOGO (09:33):
    # Live Candle 09:00.
    # Closed Candle 08:00.
    
    target_live_hour = pd.Timestamp(signal_time_str).floor('h') # e.g. 16:00
    target_closed_hour = target_live_hour - pd.Timedelta(hours=1) # e.g. 15:00
    
    live_row = df_1h[df_1h['date'] == target_live_hour]
    closed_row = df_1h[df_1h['date'] == target_closed_hour]
    
    if not closed_row.empty:
        c = closed_row.iloc[0]['close']
        e = closed_row.iloc[0]['ema50']
        print(f"Closed 1H Candle ({target_closed_hour}): Close {c} | EMA50 {e:.6f}")
        if c > e:
            print(">> CLOSED CHECK (New Logic): PASS. Trade would be valid instantly.")
        else:
            print(">> CLOSED CHECK: FAIL. Trade would be valid instantly blocked.")
            
    if not live_row.empty:
        # Check Low of live candle to see if it dipped?
        l = live_row.iloc[0]['low']
        e = live_row.iloc[0]['ema50']
        print(f"Live 1H Candle ({target_live_hour}): Low {l} | EMA50 {e:.6f}")
        
        if l <= e:
            print(">> LIVE CHECK (Old Logic): FAIL (Dipped below EMA).")
            print(">> This explains the delay! Bot waited for price to recover above EMA.")
        else:
            print(">> LIVE CHECK: PASS. (No dip found).")

if __name__ == "__main__":
    analyze_delays()
