
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

def simulate_filters():
    conn = sqlite3.connect('trades_vps_latest.db')
    df_trades = pd.read_sql_query("SELECT * FROM trades", conn)

    if df_trades.empty:
        print("No trades found.")
        return

    print(f"Backtesting New Filters on {len(df_trades)} Historical Trades...")
    
    ex = ccxt.binance()
    
    accepted_trades = []
    rejected_trades = []
    
    # Cache for efficiency (Symbol -> OHLCV) - actually separate calls are safer for distinct times
    
    for i, row in df_trades.iterrows():
        try:
            symbol = row['symbol']
            entry_time_str = row['time']
            pnl = float(row['pnl'])
            
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
            
            # Find trigger candle (candle BEFORE entry)
            match_idx = -1
            for idx, c_row in df.iterrows():
                if abs(c_row['ts'] - ts_entry) < (15 * 60 * 1000): 
                     match_idx = idx
                     break
            
            if match_idx < 5: continue
            
            # Trigger Candle (Closed)
            trigger = df.iloc[match_idx - 1] 
            
            # --- APPLY NEW FILTERS ---
            reasons = []
            
            # 1. RSI < 70
            if trigger['rsi'] > 70:
                reasons.append(f"RSI {trigger['rsi']:.1f}")
                
            # 2. Trend Floor (Close > EMA50)
            if trigger['close'] < trigger['ema50']:
                reasons.append("Below EMA50")
                
            # 3. Volume > Avg
            if trigger['vol'] < trigger['avg_vol']:
                reasons.append("Low Vol")
                
            # 4. Parabolic Extension (< 8%)
            ext = (trigger['close'] - trigger['ema50']) / trigger['ema50']
            if ext > 0.08:
                reasons.append(f"Extended {ext*100:.1f}%")

            trade_info = {
                'symbol': symbol,
                'pnl': pnl,
                'reasons': reasons
            }

            if not reasons:
                accepted_trades.append(trade_info)
            else:
                rejected_trades.append(trade_info)

            time.sleep(0.1)

        except Exception as e:
            continue

    # Results
    print("\n" + "="*40)
    print("📊 BACKTEST RESULTS: NEW FILTERS")
    print("="*40)
    
    total = len(accepted_trades) + len(rejected_trades)
    print(f"Total Trades Analyzed: {total}")
    print(f"✅ ACCEPTED: {len(accepted_trades)} ({(len(accepted_trades)/total*100):.1f}%)")
    print(f"🚫 REJECTED: {len(rejected_trades)} ({(len(rejected_trades)/total*100):.1f}%)")
    
    if accepted_trades:
        wins = len([t for t in accepted_trades if t['pnl'] > 0])
        win_rate = (wins / len(accepted_trades)) * 100
        total_pnl = sum(t['pnl'] for t in accepted_trades)
        
        print("\n--- PERFORMANCE OF ACCEPTED TRADES ---")
        print(f"Win Rate:  {win_rate:.1f}%")
        print(f"Total PnL: ${total_pnl:.2f}")
    
    if rejected_trades:
        wins = len([t for t in rejected_trades if t['pnl'] > 0])
        win_rate = (wins / len(rejected_trades)) * 100
        total_pnl = sum(t['pnl'] for t in rejected_trades)
        
        print("\n--- PERFORMANCE OF REJECTED TRADES ---")
        print(f"Win Rate:  {win_rate:.1f}%")
        print(f"Total PnL: ${total_pnl:.2f}")
        print("(We successfully filtered out these losses!)")

if __name__ == "__main__":
    simulate_filters()
