import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import sys
import os

# Add parent dir to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logic.indicators import check_volatility_ok

# --- CONFIG ---
BACKTEST_CANDLES = 1000 # ~10 days on 15m
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "LUNA/USDT", "CHZ/USDT"]
TIMEFRAME = "15m" # AlphaHunter uses 1H, BB uses 15m, Regime uses 1H
HTF = "1h"

# Risk/Exit Config
ALPHA_SL = 6.0
ALPHA_TP = 15.0
BB_SL = 2.0
BB_TP = 4.0
BREAKEVEN_GAIIN_PCT = 1.2
TRAIL_START_PCT = 2.0
TRAIL_DIST_PCT = 1.2

class QuantBacktest:
    def __init__(self, exchange):
        self.ex = exchange
        self.trades = []
        self.equity = 1000.0
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.last_ts_map = {}

    async def get_btc_regime(self):
        # In a real backtest, this should be time-synced. 
        # For simplicity, we fetch HTF BTC data for the whole period.
        ohlcv = await self.ex.fetch_ohlcv("BTC/USDT", HTF, limit=BACKTEST_CANDLES)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        return df

    def determine_regime(self, btc_row):
        ema50 = btc_row['ema50']
        ema200 = btc_row['ema200']
        if ema50 > ema200:
            diff_pct = abs(ema50 - ema200) / ema200 * 100
            if diff_pct < 0.5: return "flat"
            return "bullish"
        return "bearish"

    async def run(self):
        print(f"Starting Multi-Strategy Backtest on {len(SYMBOLS)} symbols...")
        btc_htf = await self.get_btc_regime()
        
        regime_counts = {"bullish": 0, "flat": 0, "bearish": 0}
        
        for symbol in SYMBOLS:
            print(f"Backtesting {symbol}...")
            # Fetch 15m data (base timeframe)
            ohlcv_15m = await self.ex.fetch_ohlcv(symbol, "15m", limit=BACKTEST_CANDLES)
            df_15m = pd.DataFrame(ohlcv_15m, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            
            # Fetch 1H data (AlphaHunter timeframe)
            ohlcv_1h = await self.ex.fetch_ohlcv(symbol, "1h", limit=BACKTEST_CANDLES // 4)
            df_1h = pd.DataFrame(ohlcv_1h, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])

            active_trade = None
            
            for i in range(50, len(df_15m)):
                row = df_15m.iloc[i]
                ts = row['ts']
                
                # Sync BTC Regime
                regime_row = btc_htf[btc_htf['ts'] <= ts].iloc[-1]
                regime = self.determine_regime(regime_row)
                regime_counts[regime] += 1

                # 1. Manage Active Trade
                if active_trade:
                    # Trailing Stop & Breakeven Logic
                    highest = max(active_trade['highest_price'], row['high'])
                    active_trade['highest_price'] = highest
                    
                    gain_pct = (row['high'] - active_trade['entry']) / active_trade['entry'] * 100
                    
                    # Breakeven
                    if gain_pct >= BREAKEVEN_GAIIN_PCT and active_trade['sl'] < active_trade['entry']:
                        active_trade['sl'] = active_trade['entry']
                        # print(f"  [BE] {symbol} moved to breakeven")

                    # Trailing
                    max_gain = (highest - active_trade['entry']) / active_trade['entry'] * 100
                    if max_gain >= TRAIL_START_PCT:
                        trail_sl = highest * (1 - (TRAIL_DIST_PCT / 100))
                        if trail_sl > active_trade['sl']:
                            active_trade['sl'] = trail_sl
                    
                    # Check Exit
                    if row['low'] <= active_trade['sl']:
                        # SL hit
                        pnl = (active_trade['sl'] - active_trade['entry']) / active_trade['entry']
                        self.trades.append({**active_trade, 'exit_time': ts, 'pnl': pnl, 'type': 'SL/Trail'})
                        # print(f"  [EXIT] {symbol} @ {active_trade['sl']} (PnL: {pnl*100:.2f}%)")
                        active_trade = None
                    elif row['high'] >= active_trade['tp']:
                        # TP hit
                        pnl = (active_trade['tp'] - active_trade['entry']) / active_trade['entry']
                        self.trades.append({**active_trade, 'exit_time': ts, 'pnl': pnl, 'type': 'TP'})
                        # print(f"  [EXIT] {symbol} @ {active_trade['tp']} (PnL: {pnl*100:.2f}%)")
                        active_trade = None
                    continue

                # 2. Check Entries
                if regime == "bearish": continue

                # AlphaHunter (Bullish Regime)
                if regime == "bullish":
                    # Simple mock of AlphaHunter signal (momentum)
                    # Use 1H data synced to current 15m TS
                    sub_1h = df_1h[df_1h['ts'] <= ts].iloc[-50:]
                    if len(sub_1h) < 20: continue
                    
                    # Logic: Candle Close > EMA20 and RSI > 55
                    # (Simplified version for backtest)
                    curr_1h = sub_1h.iloc[-1]
                    if curr_1h['close'] > sub_1h['close'].rolling(20).mean().iloc[-1]:
                        # Check Volatility
                        vol_ok, _ = check_volatility_ok(df_15m.iloc[i-20:i+1], '15m')
                        if vol_ok:
                            entry = row['close']
                            sl = entry * (1 - (ALPHA_SL / 100))
                            tp = entry * (1 + (ALPHA_TP / 100))
                            
                            # RRR check (15 / 6 = 2.5 > 1.8)
                            active_trade = {
                                'symbol': symbol, 'strategy': 'AlphaHunter', 'entry': entry,
                                'sl': sl, 'tp': tp, 'highest_price': entry, 'ts': ts
                            }
                            # print(f"  [ENTRY] {symbol} AlphaHunter @ {entry}")

                # Bollinger Reversion (Flat Regime)
                elif regime == "flat":
                    # Mock BB logic
                    sub_15m = df_15m.iloc[i-21:i+1]
                    sma = sub_15m['close'].rolling(20).mean()
                    std = sub_15m['close'].rolling(20).std()
                    lower = sma - (std * 2)
                    
                    curr = sub_15m.iloc[-1]
                    prev = sub_15m.iloc[-2]
                    
                    if curr['close'] > lower.iloc[-1] and prev['close'] <= lower.iloc[-2]:
                        # Confirmation: RSI Rising (simplified)
                        # Assume RSI rising if close > prev close
                        if curr['close'] > prev['close']:
                            entry = row['close']
                            sl = entry * (1 - (BB_SL / 100))
                            tp = entry * (1 + (BB_TP / 100))
                            active_trade = {
                                'symbol': symbol, 'strategy': 'Bollinger', 'entry': entry,
                                'sl': sl, 'tp': tp, 'highest_price': entry, 'ts': ts
                            }
                            # print(f"  [ENTRY] {symbol} Bollinger @ {entry}")

        self.summary(regime_counts)

    def summary(self, regime_counts):
        print("\n--- BACKTEST SUMMARY ---")
        total_ticks = sum(regime_counts.values())
        if total_ticks > 0:
            print("Regime Distribution:")
            for r, c in regime_counts.items():
                print(f"  {r}: {c/total_ticks*100:.2f}%")

        if not self.trades:
            print("No trades triggered.")
            return
            
        total_trades = len(self.trades)
        wins = [t for t in self.trades if t['pnl'] > 0]
        win_rate = (len(wins) / total_trades) * 100
        avg_pnl = np.mean([t['pnl'] for t in self.trades]) * 100
        
        print(f"Total Trades: {total_trades}")
        print(f"Win Rate: {win_rate:.2f}%")
        print(f"Average PnL: {avg_pnl:.2f}%")
        
        alpha_trades = [t for t in self.trades if t['strategy'] == 'AlphaHunter']
        bb_trades = [t for t in self.trades if t['strategy'] == 'Bollinger']
        
        if alpha_trades:
            wr_a = (len([t for t in alpha_trades if t['pnl'] > 0]) / len(alpha_trades)) * 100
            print(f"AlphaHunter: {len(alpha_trades)} trades, Win Rate: {wr_a:.2f}%")
        
        if bb_trades:
            wr_b = (len([t for t in bb_trades if t['pnl'] > 0]) / len(bb_trades)) * 100
            print(f"Bollinger: {len(bb_trades)} trades, Win Rate: {wr_b:.2f}%")

async def run_bt():
    ex = ccxt.binance()
    bt = QuantBacktest(ex)
    await bt.run()
    await ex.close()

if __name__ == "__main__":
    asyncio.run(run_bt())
