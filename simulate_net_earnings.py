
import sqlite3
import pandas as pd
import ccxt
import time
from datetime import datetime

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss.replace(0, 0.0001))
    return 100 - (100 / (1 + rs))

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def simulate_net_earnings():
    conn = sqlite3.connect('trades_new.db')
    # filtered by closed to match user's "158 trades" context
    df_trades = pd.read_sql_query("SELECT * FROM trades WHERE status='closed'", conn)

    if df_trades.empty:
        print("No closed trades found.")
        return

    print(f"Backtesting New Filters on {len(df_trades)} Closed Trades...")
    
    ex = ccxt.binance()
    
    accepted_trades = []
    rejected_trades = []
    
    for i, row in df_trades.iterrows():
        try:
            symbol = row['symbol']
            entry_time_str = row['time']
            pnl = float(row['pnl'])
            fees = float(row['fees_usd'])
            
            # Parse time
            try:
                dt_entry = datetime.fromisoformat(entry_time_str)
            except:
                dt_entry = datetime.strptime(entry_time_str, "%Y-%m-%dT%H:%M:%S.%f")
            
            ts_entry = int(dt_entry.timestamp() * 1000)
            
            # Fetch context
            since = ts_entry - (24 * 60 * 60 * 1000)
            ohlcv = ex.fetch_ohlcv(symbol, '15m', since=since, limit=100)
            if not ohlcv: continue
            
            df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            df['rsi'] = calculate_rsi(df['close'])
            df['ema50'] = calculate_ema(df['close'], 50)
            df['avg_vol'] = df['vol'].rolling(20).mean()
            
            # Find trigger candle
            match_idx = -1
            for idx, c_row in df.iterrows():
                if abs(c_row['ts'] - ts_entry) < (15 * 60 * 1000): 
                     match_idx = idx
                     break
            
            if match_idx < 5: continue
            
            # Trigger Candle (Closed)
            trigger = df.iloc[match_idx - 1] 
            
            # --- APPLY NEW FILTERS ---
            filtered_out = False
            
            # 1. RSI < 70
            if trigger['rsi'] > 70: filtered_out = True
            # 2. Trend Floor (Close > EMA50)
            if trigger['close'] < trigger['ema50']: filtered_out = True
            # 3. Volume > Avg
            if trigger['vol'] < trigger['avg_vol']: filtered_out = True
            # 4. Parabolic Extension (< 8%)
            ext = (trigger['close'] - trigger['ema50']) / trigger['ema50']
            if ext > 0.08: filtered_out = True

            trade_info = {
                'pnl': pnl,
                'fees': fees
            }

            if not filtered_out:
                accepted_trades.append(trade_info)
            else:
                rejected_trades.append(trade_info)

            time.sleep(0.05) 

        except Exception as e:
            continue

    # Results
    print("\n" + "="*40)
    print("💰 CORRECTED NET EARNINGS FORECAST")
    print("="*40)
    
    # Current Reality (All Trades)
    # DB 'pnl' is ALREADY Net (Profit - Fees)
    total_net = df_trades['pnl'].sum()
    total_fees = df_trades['fees_usd'].sum()
    
    print(f"--- CURRENT REALITY (158 Trades) ---")
    print(f"Total Fees Paid: ${total_fees:.2f}")
    print(f"REAL NET PROFIT: ${total_net:.2f}")

    # Simulated Reality (Filtered)
    sim_count = len(accepted_trades)
    # Sum of Net PnL for accepted trades
    sim_net = sum(t['pnl'] for t in accepted_trades)
    sim_fees = sum(t['fees'] for t in accepted_trades)
    
    print(f"\n--- NEW STRATEGY SIMULATION ({sim_count} Trades) ---")
    print(f"Projected Fees: ${sim_fees:.2f} (Reduced by {(1 - sim_fees/total_fees)*100:.1f}%)")
    print(f"PROJECTED NET:  ${sim_net:.2f}")
    
    diff = sim_net - total_net
    print(f"\n----------------------------------------")
    print(f"🚀 TRUE IMPROVEMENT: ${diff:.2f} Extra Profit")
    print(f"----------------------------------------")

if __name__ == "__main__":
    simulate_net_earnings()
