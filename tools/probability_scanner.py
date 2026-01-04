import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime

# CONFIG
SCAN_TIMEFRAME = '1h'
MAX_CONSOLIDATION_RANGE = 10.0 # Price range < 10% in last 24h
MIN_VOLUME_MULT = 3.0          # Current Vol > 3x Average
MAX_PRICE_CHANGE = 5.0         # Not already pumped (> 5%)

async def scan_market():
    print("=== PROBABILITY SCANNER (Finding the Next FLOW) ===")
    print(f"Criteria: Range < {MAX_CONSOLIDATION_RANGE}% | Vol > {MIN_VOLUME_MULT}x | Change < {MAX_PRICE_CHANGE}%")
    
    ex = ccxt.binance({'options': {'defaultType': 'spot'}})
    tickers = await ex.fetch_tickers()
    
    # 1. Filter candidates (USDT, Liquidity)
    candidate_symbols = []
    ignored = ["USDC", "USDP", "FDUSD", "TUSD", "EUR", "GBP"]
    
    for s, t in tickers.items():
        base = s.split('/')[0]
        if "/USDT" in s and t['quoteVolume'] > 100_000 and base not in ignored:
            candidate_symbols.append(s)
            
    print(f"Scanning {len(candidate_symbols)} pairs for Alpha...")
    
    alpha_finds = []
    
    # Batch scan
    chunk_size = 10 # Speed up
    for i in range(0, len(candidate_symbols), chunk_size):
        batch = candidate_symbols[i:i+chunk_size]
        tasks = [analyze_symbol(ex, s) for s in batch]
        results = await asyncio.gather(*tasks)
        
        for res in results:
            if res:
                alpha_finds.append(res)
                print(f" [!!!] FOUND ALPHA: {res['symbol']} (Vol: {res['vol_mult']:.1f}x, Range: {res['range']:.1f}%)")
        
        await asyncio.sleep(0.5) # Rate limit
        
    await ex.close()
    
    print("\n=== SCAN RESULTS ===")
    if not alpha_finds:
        print("No 'Pre-Pump' setups found right now.")
    else:
        alpha_finds.sort(key=lambda x: x['vol_mult'], reverse=True)
        for a in alpha_finds:
            print(f"SYMBOL: {a['symbol']}")
            print(f" - Volume Spike: {a['vol_mult']:.2f}x")
            print(f" - Consolidation: {a['range']:.2f}%")
            print(f" - Price: {a['price']}")
            print("-" * 20)

async def analyze_symbol(ex, symbol):
    try:
        # Fetch last 24h (24 candles of 1h)
        ohlcv = await ex.fetch_ohlcv(symbol, SCAN_TIMEFRAME, limit=25)
        if len(ohlcv) < 24: return None
        
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # 1. Check Consolidation (Last 24h)
        last_24 = df.iloc[-24:]
        high = last_24['high'].max()
        low = last_24['low'].min()
        price_range = ((high - low) / low) * 100
        
        if price_range > MAX_CONSOLIDATION_RANGE:
            return None # Too volatile / already pumped
            
        # 2. Check Volume Spike (Last 1h vs Avg)
        current_vol = df.iloc[-1]['vol']
        avg_vol = last_24['vol'].mean()
        
        if avg_vol == 0: return None
        vol_mult = current_vol / avg_vol
        
        if vol_mult < MIN_VOLUME_MULT:
            return None # No whale activity
            
        # 3. Check Price Change (Don't buy top)
        # Using 24h change from ticker would be faster, but we have candles
        open_24 = last_24.iloc[0]['open']
        close_now = df.iloc[-1]['close']
        change = ((close_now - open_24) / open_24) * 100
        
        if change > MAX_PRICE_CHANGE:
            return None # Already moved
            
        return {
            "symbol": symbol,
            "vol_mult": vol_mult,
            "range": price_range,
            "price": close_now
        }
        
    except Exception:
        return None

if __name__ == "__main__":
    asyncio.run(scan_market())
