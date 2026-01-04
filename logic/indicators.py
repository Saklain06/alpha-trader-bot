import pandas as pd
import numpy as np

def calculate_atr(df, window=14):
    """Calculates Average True Range."""
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(window=window).mean()

def check_volatility_ok(df, timeframe_entry='15m'):
    """
    Reject trades if:
    - ATR% < 0.6%
    - Last candle range < 0.4%
    """
    if len(df) < 15:
        return False, "Insufficient data"
        
    atr = calculate_atr(df)
    last_atr = atr.iloc[-1]
    last_price = df['close'].iloc[-1]
    atr_pct = (last_atr / last_price) * 100
    
    last_candle = df.iloc[-1]
    candle_range_pct = ((last_candle['high'] - last_candle['low']) / last_candle['low']) * 100
    
    if atr_pct < 0.6:
        return False, f"Low ATR%: {atr_pct:.2f}%"
    if candle_range_pct < 0.4:
        return False, f"Low Candle Range%: {candle_range_pct:.2f}%"
        
    return True, "Volatility OK"
