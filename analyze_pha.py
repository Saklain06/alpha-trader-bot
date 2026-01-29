
import ccxt
import pandas as pd
from datetime import datetime
import time

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss.replace(0, 0.0001))
    return 100 - (100 / (1 + rs))

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def analyze_pha():
    ex = ccxt.binance()
    symbol = "PHA/USDT"
    
    # Entry Time: 2026-01-25 15:10 UTC
    # We want candles BEFORE this.
    # 15:10 falls in the 15:00-15:15 candle (Open).
    # The signal would have triggered on the CLOSE of the 14:45-15:00 candle.
    # So we want history leading up to 15:00 UTC.
    
    # Timestamp for 15:15 UTC today
    # target_ts = 1769354100000 (roughly, let's just fetch last 24h)
    
    print(f"Fetching history for {symbol}...")
    ohlcv = ex.fetch_ohlcv(symbol, '15m', limit=100)
    
    df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
    df['date'] = pd.to_datetime(df['ts'], unit='ms')
    
    df['rsi'] = calculate_rsi(df['close'])
    df['ema50'] = calculate_ema(df['close'], 50)
    df['avg_vol'] = df['vol'].rolling(20).mean()
    
    # Locate the candle just before Entry (15:10)
    # The entry likely happened at 15:00 candle open or during it.
    # Let's look at the last 3 candles to find the trigger.
    
    print("\n--- RECENT CANDLES (For VANA Entry @ 15:10 UTC) ---")
    print(df[['date', 'close', 'rsi', 'vol']].tail(5).to_string())
    
    # Pick the likely trigger candle (Index -2 or -1 depending on fetch time)
    # Assuming script runs "now" (~15:18 UTC), the 15:15 candle is open.
    # The 15:00 candle is closed.
    # The 14:45 candle is closed.
    
    # Detailed Analysis of the "Trigger Candle" (likely 14:45 or 15:00)
    trigger_candle = df.iloc[-2] # Previous completed candle
    
    print("\n--- FORENSIC REPORT (Trigger Candle) ---")
    print(f"Time: {trigger_candle['date']}")
    print(f"Close: {trigger_candle['close']}")
    print(f"EMA50: {trigger_candle['ema50']:.4f}")
    
    # CHECKS
    # 1. RSI < 70
    rsi = trigger_candle['rsi']
    print(f"RSI:   {rsi:.2f} --> {'✅ PASS (<70)' if rsi < 70 else '❌ FAIL (>70)'}")
    
    # 2. Vol > Avg
    vol = trigger_candle['vol']
    avg_vol = trigger_candle['avg_vol']
    print(f"Vol:   {vol:.1f} (Avg: {avg_vol:.1f}) --> {'✅ PASS (>Avg)' if vol > avg_vol else '❌ FAIL (Low Vol)'}")
    
    # 3. Trend Floor (Close > EMA50)
    trend_ok = trigger_candle['close'] > trigger_candle['ema50']
    print(f"Trend: {'✅ PASS (>EMA50)' if trend_ok else '❌ FAIL (Below EMA50)'}")
    
    # 4. Parabolic Extension (< 8%)
    dist = (trigger_candle['close'] - trigger_candle['ema50']) / trigger_candle['ema50']
    print(f"Ext:   {dist*100:.2f}% --> {'✅ PASS (<8%)' if dist < 0.08 else '❌ FAIL (Parabolic)'}")
    
    print("\n--- CONCLUSION ---")
    if rsi < 70 and vol > avg_vol and trend_ok and dist < 0.08:
        print("Verdict: ✅ GOOD TRADE (Matches New Rules)")
    else:
        print("Verdict: 🛑 WOULD BE BLOCKED by New Rules")

if __name__ == "__main__":
    analyze_pha()
