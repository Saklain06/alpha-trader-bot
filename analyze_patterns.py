
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

def analyze_patterns():
    conn = sqlite3.connect('trades_vps_latest.db')
    df_trades = pd.read_sql_query("SELECT * FROM trades WHERE status='closed'", conn)
    
    if df_trades.empty:
        print("No closed trades found.")
        return

    # Sort by PnL
    df_trades['pnl'] = pd.to_numeric(df_trades['pnl'])
    df_trades = df_trades.sort_values('pnl', ascending=False)
    
    # Top 5 Winners & Bottom 5 Losers
    winners = df_trades.head(5)
    losers = df_trades.tail(5)
    
    targets = pd.concat([winners, losers])
    
    print(f"Analyzing {len(targets)} Extremes (5 Best, 5 Worst)...")
    
    ex = ccxt.binance()
    
    results = []

    for i, row in targets.iterrows():
        try:
            symbol = row['symbol']
            entry_time_str = row['time']
            pnl = row['pnl']
            
             # Parse time
            try:
                dt_entry = datetime.fromisoformat(entry_time_str)
            except:
                dt_entry = datetime.strptime(entry_time_str, "%Y-%m-%dT%H:%M:%S.%f")

            ts_entry = int(dt_entry.timestamp() * 1000)
            since = ts_entry - (24 * 60 * 60 * 1000)
            
            ohlcv = ex.fetch_ohlcv(symbol, '15m', since=since, limit=100)
            if not ohlcv: continue
            
            df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            
            # Indicators
            df['rsi'] = calculate_rsi(df['close'])
            df['ema50'] = calculate_ema(df['close'], 50)
            df['avg_vol'] = df['vol'].rolling(20).mean()
            
            # Match Entry Candle
            match_idx = -1
            for idx, c_row in df.iterrows():
                if abs(c_row['ts'] - ts_entry) < (15 * 60 * 1000): 
                     match_idx = idx
                     break
            
            if match_idx < 5: continue
            
            # Entry Context (Candle prior to entry usually triggers it)
            entry_c = df.iloc[match_idx]
            prev_c = df.iloc[match_idx - 1] # Trigger Candle
            
            rsi_val = prev_c['rsi']
            rel_vol = prev_c['vol'] / prev_c['avg_vol'] if prev_c['avg_vol'] > 0 else 1.0
            trend_dist = (prev_c['close'] - prev_c['ema50']) / prev_c['ema50'] * 100 # % above EMA50
            
            tag = "WINNER 🏆" if pnl > 0 else "LOSER ❌"
            
            results.append({
                "Symbol": symbol,
                "Type": tag,
                "PnL": pnl,
                "RSI": rsi_val,
                "RelVol": rel_vol,
                "Trend%": trend_dist
            })
            
            time.sleep(0.1)
            
        except Exception as e:
            print(f"Error {row['symbol']}: {e}")

    # Print Report
    res_df = pd.DataFrame(results)
    print("\n=== PATTERN ANALYSIS ===")
    print(res_df.to_string(index=False, float_format="%.2f"))
    
    # Averages
    print("\n=== AVERAGES ===")
    print(res_df.groupby("Type")[['RSI', 'RelVol', 'Trend%']].mean())

if __name__ == "__main__":
    analyze_patterns()
