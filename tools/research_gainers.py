import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# CONFIG
TIMEFRAME = '15m'
LOOKBACK_DAYS = 3 # Analyze gainers from last 3 days
PRE_PUMP_WINDOW = 24 * 4 # Look at 24h before the pump (15m candles)

async def main():
    print("=== GAINER PATTERN RESEARCH ===")
    print("1. Identifying recent Top Gainers...")
    
    ex = ccxt.bingx({'options': {'defaultType': 'spot'}})
    tickers = await ex.fetch_tickers()
    
    # Filter for active USDT pairs
    candidates = []
    for s, t in tickers.items():
        if "/USDT" in s and t['quoteVolume'] > 500_000: # Decent liquidity
            candidates.append(t)
            
    # Sort by 24h Change (Percentage)
    candidates.sort(key=lambda x: float(x['percentage'] or 0), reverse=True)
    top_gainers = candidates[:5] # Top 5
    
    print(f"\nTop 5 Gainers (24h):")
    for t in top_gainers:
        print(f" - {t['symbol']}: +{t['percentage']}%")
        
    print("\n2. Analyzing 'Pre-Pump' Data...")
    print("(Searching for patterns occurring 24h BEFORE the peak)")
    
    for t in top_gainers:
        symbol = t['symbol']
        try:
            # Fetch 3 days of data
            ohlcv = await ex.fetch_ohlcv(symbol, TIMEFRAME, limit=300)
            df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            
            # Find the "Pump" moment (Highest High)
            pump_idx = df['high'].idxmax()
            pump_price = df['high'].iloc[pump_idx]
            
            # Go back 24h from pump to see what happened BEFORE
            start_idx = max(0, pump_idx - 96) # 96 * 15m = 24h
            if start_idx >= pump_idx: continue
            
            pre_pump_df = df.iloc[start_idx:pump_idx]
            
            # CALCULATE METRICS
            # 1. Volume Anomaly: Max vol vs Avg vol
            avg_vol = pre_pump_df['vol'].mean()
            max_vol = pre_pump_df['vol'].max()
            vol_spike = max_vol / avg_vol if avg_vol > 0 else 0
            
            # 2. Consolidation: Price Range (High - Low) / Low
            highest = pre_pump_df['high'].max()
            lowest = pre_pump_df['low'].min()
            range_pct = ((highest - lowest) / lowest) * 100
            
            # 3. RSI Trend (Slope)
            delta = pre_pump_df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            avg_rsi = rsi.mean()
            
            print(f"\n[ANALYSIS] {symbol} (Pre-Pump Stats):")
            print(f" - Consolidation Range: {range_pct:.2f}% (Over 24h)")
            print(f" - Volume Anomaly:      {vol_spike:.2f}x (Spike vs Avg)")
            print(f" - Average RSI:         {avg_rsi:.2f}")
            
        except Exception as e:
            print(f"Error {symbol}: {e}")
            
    await ex.close()
    print("\n=== CONCLUSION ===")
    print("If we see low 'Consolidation Range' and high 'Volume Anomaly',")
    print("that is a valid pattern to scan for.")

if __name__ == "__main__":
    asyncio.run(main())
