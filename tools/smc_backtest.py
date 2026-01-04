import asyncio
import ccxt.async_support as ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# Add parent dir to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logic.smc_utils import find_fvgs, find_order_blocks

# CONFIG
TIMEFRAME = '15m'
HTF = '1h'
SYMBOL_COUNT = 5
BACKTEST_CANDLES = 500 # Approx 5 days on 15m
SL_PCT = 0.01 # 1% Stop Loss
TP_PCT = 0.03 # 3% Take Profit (Sniper)

async def get_top_gainers(ex):
    print("Scanning for top gainers...")
    tickers = await ex.fetch_tickers()
    candidates = []
    for s, t in tickers.items():
        if "/USDT" in s and t['quoteVolume'] > 1_000_000: # $1M+ Vol
            candidates.append(t)
    
    candidates.sort(key=lambda x: float(x['percentage'] or 0), reverse=True)
    return candidates[:SYMBOL_COUNT]

async def backtest_symbol(ex, symbol):
    print(f"Backtesting {symbol}...")
    try:
        # Fetch data
        ohlcv = await ex.fetch_ohlcv(symbol, TIMEFRAME, limit=BACKTEST_CANDLES)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        df['dt'] = pd.to_datetime(df['ts'], unit='ms')
        
        # Find SMC Patterns
        fvgs = find_fvgs(df)
        obs = find_order_blocks(df, fvgs)
        
        trades = []
        equity = 1000
        balance = equity
        
        active_trade = None
        
        for i in range(50, len(df)):
            row = df.iloc[i]
            
            # Check for Exit
            if active_trade:
                if row['low'] <= active_trade['sl']:
                    # SL Hit
                    pnl = (active_trade['sl'] - active_trade['entry']) / active_trade['entry']
                    balance += balance * pnl
                    active_trade['exit_price'] = active_trade['sl']
                    active_trade['pnl'] = pnl
                    trades.append(active_trade)
                    active_trade = None
                elif row['high'] >= active_trade['tp']:
                    # TP Hit
                    pnl = (active_trade['tp'] - active_trade['entry']) / active_trade['entry']
                    balance += balance * pnl
                    active_trade['exit_price'] = active_trade['tp']
                    active_trade['pnl'] = pnl
                    trades.append(active_trade)
                    active_trade = None
                continue

            # Check for Entry (Sniper Entry into Bullish OB)
            # Find recent valid OBs (within last 24 bars)
            recent_obs = [ob for ob in obs if ob['index'] < i and ob['index'] > i - 24 and ob['type'] == 'bullish']
            
            for ob in recent_obs:
                # Entry Price is top of OB
                entry_price = ob['top']
                
                # Check if price has entered the OB range in this candle
                if row['low'] <= entry_price and row['close'] > ob['bottom']:
                    # Sniper Entry
                    sl = ob['bottom'] * 0.995 # SL slightly below OB bottom
                    tp = entry_price * (1 + TP_PCT)
                    
                    active_trade = {
                        'symbol': symbol,
                        'entry': entry_price,
                        'sl': sl,
                        'tp': tp,
                        'entry_time': row['dt']
                    }
                    # Mark OB as mitigated (simplified)
                    ob['mitigated'] = True
                    break
        
        return trades, balance
    except Exception as e:
        print(f"Error backtesting {symbol}: {e}")
        return [], 0

async def main():
    ex = ccxt.binance()
    top_gainers = await get_top_gainers(ex)
    
    all_trades = []
    total_balance = 0
    
    print(f"\nResults for Top {SYMBOL_COUNT} Gainers Strategy:")
    for t in top_gainers:
        symbol = t['symbol']
        trades, final_balance = await backtest_symbol(ex, symbol)
        all_trades.extend(trades)
        total_balance += final_balance
        
        win_rate = 0
        if trades:
            wins = len([tr for tr in trades if tr['pnl'] > 0])
            win_rate = (wins / len(trades)) * 100
            
        print(f"{symbol}: Trades: {len(trades)}, Win Rate: {win_rate:.2f}%, Final: ${final_balance:.2f}")
        
    print(f"\nOverall Summary:")
    print(f"Total Trades: {len(all_trades)}")
    if all_trades:
        avg_pnl = np.mean([tr['pnl'] for tr in all_trades]) * 100
        print(f"Average PnL per trade: {avg_pnl:.2f}%")
        
    await ex.close()

if __name__ == "__main__":
    asyncio.run(main())
