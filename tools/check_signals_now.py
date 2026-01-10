import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import sys
import os
sys.path.append(os.getcwd())

from tabulate import tabulate
from logic.smc_utils import SMCManager

async def check_signals_now():
    ex = ccxt.binance()
    print("Fetching Top Gainers...")
    tickers = await ex.fetch_tickers()
    candidates = []
    for s, t in tickers.items():
        if "/USDT" in s and t['quoteVolume'] > 1_000_000:
            candidates.append(t)
    
    candidates.sort(key=lambda x: float(x['percentage'] or 0), reverse=True)
    targets = [t['symbol'] for t in candidates[:15]]
    print(f"Top 15 Targets: {targets}")
    
    try:
        results = []
        for symbol in targets:
            # Fetch OHLCV
            ohlcv = await ex.fetch_ohlcv(symbol, '15m', limit=200)
            
            # Use 1h alignment for Trend
            ohlcv_1h = await ex.fetch_ohlcv(symbol, '1h', limit=210)
            
            # Calculate Trend (Manually matching main.py)
            df_1h = pd.DataFrame(ohlcv_1h, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            df_1h['ema50'] = df_1h['close'].ewm(span=50, adjust=False).mean()
            df_1h['ema200'] = df_1h['close'].ewm(span=200, adjust=False).mean()
            
            last_close = df_1h['close'].iloc[-1]
            last_ema50 = df_1h['ema50'].iloc[-1]
            last_ema200 = df_1h['ema200'].iloc[-1]
            
            trend_bullish = (last_close > last_ema50) and (last_close > last_ema200)
            
            # Now Check Signal
            valid, diag = SMCManager.check_signal(symbol, ohlcv, trend_bullish=trend_bullish)
            
            results.append({
                "symbol": symbol,
                "price": last_close,
                "trend_ok": "✅" if trend_bullish else "❌",
                "valid": "✅" if valid else "❌",
                "reason": diag.get("reason", "N/A"),
                "rsi": diag.get("rsi", "N/A"),
                "vol": diag.get("vol_msg", "OK")
            })
            
        print(tabulate(results, headers="keys", tablefmt="psql"))

    except Exception as e:
        print(f"Error: {e}")
    finally:
        await ex.close()

if __name__ == "__main__":
    asyncio.run(check_signals_now())
