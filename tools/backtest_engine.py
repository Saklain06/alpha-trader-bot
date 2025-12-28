import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta

# CONFIG
FEES_PCT = 0.001       # 0.1%
SLIPPAGE_PCT = 0.001   # 0.1%
INITIAL_BALANCE = 1000.0
TRAIL_TRIGGER = 0.015  # +1.5%
TRAIL_DIST = 0.02      # 2%
STATIC_SL = 0.04       # 4% (Reverted to standard)
TIMEFRAME = '1h'       # CHANGED TO 1H
DAYS = 30

class BacktestEngine:
    def __init__(self, balance=INITIAL_BALANCE):
        self.balance = balance
        self.equity = balance
        self.trades = []
        self.open_trades = []
        self.history = []

    async def fetch_data(self, symbol):
        filename = f"data/{symbol.replace('/', '_')}_{TIMEFRAME}.csv"
        os.makedirs("data", exist_ok=True)
        
        if os.path.exists(filename):
            print(f"Loading {symbol} from cache...")
            df = pd.read_csv(filename)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            return df
        
        print(f"Fetching {symbol} from BingX...")
        # FIX: Explicitly set spot
        ex = ccxt.bingx({
            'options': {'defaultType': 'spot'}
        })
        
        # Start 30 days ago
        start_ts = int((datetime.now() - timedelta(days=DAYS)).timestamp() * 1000)
        all_ohlcv = []
        
        try:
            while True:
                # BingX limit is usually 1000 or 1440
                ohlcv = await ex.fetch_ohlcv(symbol, TIMEFRAME, since=start_ts, limit=1000)
                if not ohlcv: break
                
                # Check if we got new data
                if all_ohlcv and ohlcv[-1][0] == all_ohlcv[-1][0]:
                    break
                    
                all_ohlcv += ohlcv
                start_ts = ohlcv[-1][0] + 1
                
                # Stop if we reached now
                if start_ts > datetime.now().timestamp() * 1000:
                    break
                    
                print(f"Fetched {len(all_ohlcv)} candles...")
                await asyncio.sleep(0.2)
        except Exception as e:
            print(f"Fetch Error: {e}")
        finally:
            await ex.close()
            
        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.to_csv(filename, index=False)
        return df

    def run(self, symbol, df):
        print(f"Running backtest for {symbol} ({len(df)} candles)...")
        
        # Pre-calc indicators
        df['pct_change'] = df['close'].pct_change(periods=24*4) * 100 # Approx 24h change
        df['vol_ma'] = df['volume'].rolling(20).mean()
        
        # Calculate RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        for i in range(50, len(df)):
            curr = df.iloc[i]
            prev = df.iloc[i-1]
            
            # 1. CHECK EXITS (Intra-candle simulation)
            for t in list(self.open_trades):
                self.check_exit(t, curr)
                
    def run(self, symbol, df, strategy_name="momentum"):
        print(f"Running {strategy_name} for {symbol} ({len(df)} candles)...")
        
        # Pre-calc indicators
        df['pct_change'] = df['close'].pct_change(periods=24*4) * 100 
        df['vol_ma'] = df['volume'].rolling(20).mean()
        
        # EMA
        df['ema_fast'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean() # LONG TERM FILTER
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        for i in range(200, len(df)): # Need 200 candles for EMA 200
            curr = df.iloc[i]
            prev = df.iloc[i-1]
            
            # 1. CHECK EXITS
            for t in list(self.open_trades):
                self.check_exit(t, curr)
                
            # 2. CHECK ENTRIES
            if len(self.open_trades) == 0:
                signal = False
                
                # --- STRATEGY 1: MOMENTUM (Original) ---
                if strategy_name == "momentum":
                    is_uptrend = curr['pct_change'] > 3.0 and curr['pct_change'] < 25.0
                    vol_spike = curr['volume'] > (curr['vol_ma'] * 3.0) if 'vol_ma' in curr else True
                    signal = is_uptrend and vol_spike
                
                # --- STRATEGY 2: MEAN REVERSION (Oversold) ---
                elif strategy_name == "mean_reversion":
                    # Buy when RSI < 30 (Fear)
                    signal = curr['rsi'] < 30
                    
                # --- STRATEGY 3: EMA TREND (OPTIMIZED) ---
                elif strategy_name == "ema_trend":
                    # Golden Cross (Fast crosses above Slow)
                    cross_up = prev['ema_fast'] <= prev['ema_slow'] and curr['ema_fast'] > curr['ema_slow']
                    # Trend Filter: Price must be above EMA 200 (Bull Market Check)
                    trend_ok = curr['close'] > curr['ema_200']
                    
                    signal = cross_up and trend_ok
                    
                # --- STRATEGY 4: BOLLINGER REVERSION ---
                elif strategy_name == "bollinger_reversion":
                    # Calc BB (20, 2)
                    sma = df['close'].rolling(20).mean()
                    std = df['close'].rolling(20).std()
                    lower = sma - (std * 2)
                    
                    # Buy Dip: Price < Lower Band AND RSI < 30
                    is_dip = curr['close'] < lower.iloc[i]
                    is_oversold = curr['rsi'] < 30
                    
                    signal = is_dip and is_oversold
                    
                # --- STRATEGY 5: ALPHA HUNTER (Volume + Consolidation) ---
                elif strategy_name == "alpha_hunter":
                    # Need at least 24h of history
                    if i < 24: 
                        signal = False
                    else:
                        # 1. Consolidation (Last 24h)
                        last_24 = df.iloc[i-24:i]
                        high_24 = last_24['high'].max()
                        low_24 = last_24['low'].min()
                        range_pct = ((high_24 - low_24) / low_24) * 100
                        
                        is_consolidating = range_pct < 10.0
                        
                        # 2. Volume Spike (Current vs Avg 24h)
                        avg_vol = last_24['volume'].mean()
                        curr_vol = curr['volume']
                        vol_mult = curr_vol / avg_vol if avg_vol > 0 else 0
                        
                        is_vol_spike = vol_mult > 3.0
                        
                        # 3. Not Pumped (Price Change < 5% in 24h)
                        open_24 = last_24.iloc[0]['open']
                        change_24 = ((curr['close'] - open_24) / open_24) * 100
                        is_early = change_24 < 5.0
                        
                        signal = is_consolidating and is_vol_spike and is_early

                if signal:
                    if i + 1 < len(df):
                        entry_price = df.iloc[i+1]['open']
                        self.open_trade(symbol, entry_price, curr['timestamp'], strategy_name)

    def open_trade(self, symbol, price, time, strategy):
        # Position Sizing: 10% of equity
        size_usd = self.equity * 0.1
        qty = size_usd / price
        
        # Apply Slippage & Fees
        entry_price = price * (1 + SLIPPAGE_PCT)
        cost_usd = qty * entry_price
        fees = cost_usd * FEES_PCT
        
        # TP/SL varies by strategy
        sl_pct = STATIC_SL
        if strategy == "mean_reversion":
            sl_pct = 0.05 # Wider stop for catching knives
        
        trade = {
            "symbol": symbol,
            "entry_price": entry_price,
            "qty": qty,
            "sl": entry_price * (1 - sl_pct),
            "tp": 0, 
            "trail_active": False,
            "trail_sl": 0,
            "highest": entry_price,
            "status": "open",
            "entry_time": time,
            "fees": fees
        }
        self.open_trades.append(trade)

    def check_exit(self, t, row):
        low = row['low']
        high = row['high']
        
        # Update High & Trail
        if high > t['highest']:
            t['highest'] = high
        
        # Dynamic Trail
        gain = (high - t['entry_price']) / t['entry_price']
        if not t['trail_active'] and gain >= TRAIL_TRIGGER:
            t['trail_active'] = True
            t['trail_sl'] = t['highest'] * (1 - TRAIL_DIST)
        
        if t['trail_active']:
            new_trail = t['highest'] * (1 - TRAIL_DIST)
            if new_trail > t['trail_sl']:
                t['trail_sl'] = new_trail
        
        exit_price = None
        reason = ""
        
        if low <= t['sl']:
            exit_price = t['sl'] * (1 - SLIPPAGE_PCT)
            reason = "SL"
        elif t['trail_active'] and low <= t['trail_sl']:
            exit_price = t['trail_sl'] * (1 - SLIPPAGE_PCT)
            reason = "Trail"
        
        if exit_price:
            self.close_trade(t, exit_price, reason)

    def close_trade(self, t, price, reason):
        full_value = t['qty'] * price
        fees = full_value * FEES_PCT
        pnl = full_value - (t['qty'] * t['entry_price']) - t['fees'] - fees
        self.equity += pnl 
        res = {
            **t,
            "exit_price": price,
            "exit_reason": reason,
            "pnl": pnl,
            "pnl_pct": (pnl / (t['qty'] * t['entry_price'])) * 100,
            "status": "closed"
        }
        if res["pnl_pct"] > 500:
             print(f"[CRAZY TRADE] {t['symbol']} Entry: {t['entry_price']} Exit: {price} PnL: {res['pnl_pct']}%")
        self.trades.append(res)
        self.open_trades.remove(t)

    def report(self):
        if not self.trades:
            print(f"No trades.")
            return

        wins = [t for t in self.trades if t['pnl'] > 0]
        losses = [t for t in self.trades if t['pnl'] <= 0]
        
        win_rate = len(wins) / len(self.trades) * 100
        total_pnl = sum(t['pnl'] for t in self.trades)
        profit_factor = sum(t['pnl'] for t in wins) / abs(sum(t['pnl'] for t in losses)) if losses else 999
        
        print(f"Trades: {len(self.trades):<4} | WR: {win_rate:<5.1f}% | PnL: ${total_pnl:<6.2f} | PF: {profit_factor:.2f}")

async def main():
    engine = BacktestEngine()
    symbols = ["BAT/USDT", "NMR/USDT", "PEPE/USDT", "LUNC/USDT", "BTC/USDT"]
    strategies = ["alpha_hunter", "bollinger_reversion"]
    
    # Cache data first
    data_map = {}
    for s in symbols[1:]:
        try:
            data_map[s] = await engine.fetch_data(s)
        except: pass
        
    print("\n=== STRATEGY TOURNAMENT ===")
    for strat in strategies:
        print(f"\nEvaluating: {strat.upper()}")
        for s, df in data_map.items():
            engine = BacktestEngine() # Reset for each symbol to avoid cross-contamination
            engine.run(s, df, strat)
            engine.report()

if __name__ == "__main__":
    asyncio.run(main())
