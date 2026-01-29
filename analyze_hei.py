
import ccxt
import pandas as pd
from datetime import datetime
import time

def analyze_hei():
    ex = ccxt.binance()
    symbol = "HEI/USDT"
    
    print(f"Fetching history for {symbol}...")
    
    # 1. Fetch 15m Data (Signal)
    ohlcv = ex.fetch_ohlcv(symbol, '15m', limit=100)
    df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
    df['date'] = pd.to_datetime(df['ts'], unit='ms')
    df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # 2. Fetch 1H Data (Trend Context)
    ohlcv_1h = ex.fetch_ohlcv(symbol, '1h', limit=50)
    df_1h = pd.DataFrame(ohlcv_1h, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
    df_1h['date'] = pd.to_datetime(df_1h['ts'], unit='ms')
    df_1h['ema50'] = df_1h['close'].ewm(span=50, adjust=False).mean()

    print("\n--- 1H Trend Forensic Analysis ---")
    # Check the 06:00 Candle (which determines Trend at 07:00 Open)
    target_1h = pd.Timestamp("2026-01-26 06:00:00")
    row_1h = df_1h[df_1h['date'] == target_1h]
    
    if not row_1h.empty:
        c = row_1h.iloc[0]['close']
        e = row_1h.iloc[0]['ema50']
        print(f"06:00 Candle (Closed at 07:00): Close {c} | EMA50 {e:.6f}")
        
        if c > e:
            print(">> Qualification Status at 07:00: VALID (Trend established).")
            print(">> If entry was late, it was NOT due to trend check (unless data latency).")
        else:
            print(">> Qualification Status at 07:00: INVALID (Close <= EMA50).")
            print(">> This explains the delay! The bot waited for the 07:00 candle to pump above EMA.")
            
            # Check 07:00 Candle
            target_1h_next = pd.Timestamp("2026-01-26 07:00:00")
            row_next = df_1h[df_1h['date'] == target_1h_next]
            if not row_next.empty:
                 c_next = row_next.iloc[0]['close']
                 e_next = row_next.iloc[0]['ema50']
                 print(f"07:00 Candle (Live at Entry): Close {c_next} | EMA50 {e_next:.6f}")
                 if c_next > e_next:
                     print(">> Trend became VALID during the 07:00 hour (Pumped).")
    else:
        print("Could not find 06:00 1H candle.")

    print("\n--- 15m Signal Analysis ---")
    # Check Reclaim Candle (06:45)
    target_15m = pd.Timestamp("2026-01-26 06:45:00")
    reclaim_candle = df[df['date'] == target_15m]
    
    if not reclaim_candle.empty:
        row = reclaim_candle.iloc[0]
        c = row['close']
        ema5 = row['ema5']
        val = c > ema5
        print(f"06:45 Candle (Reclaim): Close {c} | EMA5 {ema5:.6f} | Valid: {val}")
        
    # ... (previous code) ...
    # 3. Fetch BTC Data for Relative Strength
    print("Fetching BTC history...")
    btc_ohlcv = ex.fetch_ohlcv("BTC/USDT", '1h', limit=50) # Fetch enough for context
    df_btc = pd.DataFrame(btc_ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
    df_btc['date'] = pd.to_datetime(df_btc['ts'], unit='ms')
    
    print("\n--- Forensic Analysis of Filters ---")
    
    # 1. Check RSI & Vol & Extension on Reclaim Candle (06:45)
    target_15m = pd.Timestamp("2026-01-26 06:45:00")
    reclaim = df[df['date'] == target_15m]
    
    if not reclaim.empty:
        r = reclaim.iloc[0]
        # Calculate RSI manually for that point if needed or assume df has it
        # We need to calc RSI on the df first
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss.replace(0, 0.0001))
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # Recalculate Avg Vol
        df['avg_vol'] = df['vol'].rolling(20).mean()
        
        rsi_val = df.loc[df['date'] == target_15m, 'rsi'].values[0]
        vol_val = df.loc[df['date'] == target_15m, 'vol'].values[0]
        avg_vol_val = df['avg_vol'].shift(1).loc[df['date'] == target_15m].values[0] # Shift 1 to match "iloc[-2]" logic for rolling?
        # distinct logic in strategy: df['vol'].rolling(20).mean().iloc[-2] means avg of previous 20 excluding current?
        # strategy: avg_vol = df['vol'].rolling(20).mean().iloc[-2]. 
        # Actually standard rolling includes current. iloc[-2] is the Reclaim candle.
        # So it compares Reclaim Vol vs Aug Vol (including Reclaim).
        # Wait, strategy says: "Avg of previous 20".
        # If we use rolling(20).mean().iloc[-2], it includes the candle at -2.
        
        print(f"Reclaim RSI: {rsi_val:.2f} (Limit 70)")
        print(f"Reclaim Vol: {vol_val:.1f} vs Avg {avg_vol_val:.1f}")
        
        ema50_15m = df.loc[df['date'] == target_15m, 'ema50'].values[0]
        dist = (r['close'] - ema50_15m) / ema50_15m
        print(f"Extension: {dist*100:.2f}% (Limit 8%)")

    # 3. Momentum Filter Check
    # Rule: Reclaim Close > Pullback High
    # Reclaim = 06:45 (row[-2]). Pullback = 06:30 (row[-3]).
    
    target_pullback = pd.Timestamp("2026-01-26 06:30:00")
    pullback_candle = df[df['date'] == target_pullback]
    
    if not reclaim.empty and not pullback_candle.empty:
        r_close = reclaim.iloc[0]['close']
        p_high = pullback_candle.iloc[0]['high']
        print(f"Reclaim Close (06:45): {r_close}")
        print(f"Pullback High (06:30): {p_high}")
        
        if r_close > p_high:
            print(">> MOMENTUM PASS: Reclaim Close > Pullback High")
        else:
            print(">> MOMENTUM FAIL: Reclaim Low <= Pullback High")
            print(">> This would BLOCK the trade!")

    # 4. Check 1H Low for potential Trend Dip
    if not row_1h.empty:
        low_1h = row_1h.iloc[0]['low']
        ema50_1h = row_1h.iloc[0]['ema50'] # Note: EMA is calc based on Close usually, but trend check compares Close vs EMA.
        # However, if using Live Candle (iloc[-1]), Close = Current Price.
        # If Current Price dipped below EMA, it fails.
        # So check if Low < EMA.
        print(f"1H Candle Low: {low_1h} | EMA50: {ema50_1h:.6f}")
        if low_1h <= ema50_1h:
             print(">> TREND DIP RISK: 1H Low touched/broke EMA50.")
             print(">> If strategy used iloc[-1] (Live), this could disqualify temporarily!")
        else:
             print(">> TREND SAFE: 1H Low stayed above EMA50.")
    
    try:
        # Fetch 24h ago candles
        start_ts = int(target_1h.timestamp() * 1000) - (24 * 60 * 60 * 1000)
        
        # HEI 24h ago
        hei_old = ex.fetch_ohlcv(symbol, '1h', limit=1, params={'endTime': start_ts + 60000})
        hei_now = row_1h.iloc[0]['close']  # Close at 07:00 (which is 06:00 candle close?)
        # checking "Live" price at 07:00 means Close of 06:00 candle? 
        # No, ticker % change is usually based on Rolling 24h.
        # So (Price Now / Price 24h Ago) - 1.
        
        if hei_old:
             hei_old_close = hei_old[0][4]
             hei_pct = (hei_now - hei_old_close) / hei_old_close * 100
             print(f"HEI 24h Change approx: {hei_pct:.2f}%")
        
        # BTC 24h ago
        btc_old = ex.fetch_ohlcv("BTC/USDT", '1h', limit=1, params={'endTime': start_ts + 60000})
        # BTC Now (07:00)
        btc_row = df_btc[df_btc['date'] == target_1h]
        if not btc_row.empty and btc_old:
             btc_now = btc_row.iloc[0]['close']
             btc_old_close = btc_old[0][4]
             btc_pct = (btc_now - btc_old_close) / btc_old_close * 100
             print(f"BTC 24h Change approx: {btc_pct:.2f}%")
             
             if hei_pct <= btc_pct:
                 print(">> RELATIVE STRENGTH BLOCK: HEI was weaker than BTC at 07:00.")
             else:
                 print(">> RELATIVE STRENGTH PASS: HEI was stronger.")
                 
    except Exception as e:
        print(f"Could not calc relative strength: {e}")

if __name__ == "__main__":
    analyze_hei()
