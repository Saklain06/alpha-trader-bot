"""
mvp_crypto_bot.py
Single-file MVP: backtest + paper-live + real-live (via ccxt).
Usage:
  - Edit CONFIG below
  - Run: python mvp_crypto_bot.py --backtest
  - Run paper-live (paper simulated): python mvp_crypto_bot.py --paper
  - Run live (careful): python mvp_crypto_bot.py --live

Defaults: EMA(8/21) + RSI(14) + volume spike. Timeframe 1m or 5m.
"""
import ccxt, time, math, argparse, csv, os, sys
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from stats_writer import write_stats


load_dotenv()

print("📁 Writing trades to:", os.path.abspath("trades_log.csv"))





# ------------- CONFIG -------------
CONFIG = {
    "exchange": "bingx",           # "binance" or "bingx" (ccxt id)
    "symbol": "BTC/USDT",
    "timeframe": "1m",              # 1m, 3m, 5m, 15m...
    "since_minutes": 1000,          # how much history to fetch for backtest
    "balance_usdt": 1000,           # simulated starting balance
    "risk_per_trade": 0.01,         # 1% risk per trade
    "ema_fast": 8,
    "ema_slow": 21,
    "rsi_period": 14,
    "volume_mult": 1.8,             # volume spike multiplier
    "paper_mode": True,             # default true
    "api_key": "",
    "api_secret": "",
    "max_concurrent": 1,            # concurrent positions
    "sl_pct": 0.6,                  # 0.6% SL default
    "tp_pct": 1.2,                  # 1.2% TP default
    "order_size_pct": 0.5,          # fraction of available balance to use per position
}

# ------------- HELPERS -------------
def init_exchange(cfg):
    ex_class = getattr(ccxt, cfg['exchange'])
    ex = ex_class({
        'apiKey': os.getenv("BINGX_API_KEY"),
        'secret': os.getenv("BINGX_SECRET"),
        'enableRateLimit': True,
    })
    return ex



def fetch_ohlcv(ex, symbol, timeframe, limit=500):
    # return pandas DataFrame with columns: ts, open, high, low, close, volume
    data = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(data, columns=['ts','open','high','low','close','volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    return df

# indicators
def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(alpha=1/period, adjust=False).mean()
    ma_down = down.ewm(alpha=1/period, adjust=False).mean()
    rs = ma_up / (ma_down + 1e-9)
    return 100 - (100 / (1 + rs))

# strategy signals (returns DataFrame with signals)
def generate_signals(df, cfg):
    df = df.copy()
    df['ema_fast'] = ema(df['close'], cfg['ema_fast'])
    df['ema_slow'] = ema(df['close'], cfg['ema_slow'])
    df['rsi'] = rsi(df['close'], cfg['rsi_period'])
    df['vol_ma'] = df['volume'].rolling(20).mean()
    df['vol_spike'] = df['volume'] > (df['vol_ma'] * cfg['volume_mult'])
    # entry: fast > slow, rsi between 30 and 70 bounce, volume spike
    df['long_entry'] = (df['ema_fast'] > df['ema_slow']) & (df['rsi'] > 40) & (df['rsi'] < 80) & df['vol_spike']
    # exit: price hits TP/SL handled in backtest
    return df

# backtester
def backtest(df, cfg, verbose=False):
    balance = cfg['balance_usdt']
    equity = balance
    position = None
    trades = []
    for i in range(1, len(df)):
        row = df.iloc[i]
        if position is None and row['long_entry']:
            entry_price = row['close']
            sl = entry_price * (1 - cfg['sl_pct']/100)
            tp = entry_price * (1 + cfg['tp_pct']/100)
            # position sizing: use order_size_pct of balance
            usd_to_risk = balance * cfg['order_size_pct']
            qty = usd_to_risk / entry_price
            position = {'entry_index': i, 'entry_price': entry_price, 'sl': sl, 'tp': tp, 'qty': qty}
            if verbose: print(f"Entry @ {entry_price:.2f} sl {sl:.2f} tp {tp:.2f}")
        elif position is not None:
            # check if sl or tp hit in this candle's high/low
            low = row['low']; high = row['high']
            closed = False; exit_price=None; reason=''
            if low <= position['sl']:
                exit_price = position['sl']; reason='SL'
                closed=True
            elif high >= position['tp']:
                exit_price = position['tp']; reason='TP'
                closed=True
            # simple exit if ema_fast crosses below ema_slow
            elif row['ema_fast'] < row['ema_slow']:
                exit_price = row['close']; reason='trend_break'
                closed=True
            if closed:
                pnl = (exit_price - position['entry_price']) * position['qty']
                balance += pnl
                trades.append({'entry':position['entry_price'],'exit':exit_price,'pnl':pnl,'reason':reason})
                if verbose: print(f"Exit @ {exit_price:.2f} pnl {pnl:.2f} reason {reason}")
                position = None
    # metrics
    win_trades = [t for t in trades if t['pnl']>0]
    loss_trades = [t for t in trades if t['pnl']<=0]
    total_pnl = sum(t['pnl'] for t in trades)
    win_rate = len(win_trades)/len(trades) if trades else 0
    profit_factor = sum(t['pnl'] for t in win_trades)/(-sum(t['pnl'] for t in loss_trades)+1e-9) if loss_trades else float('inf')
    results = {
        'trades': trades,
        'total_pnl': total_pnl,
        'final_balance': balance,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'num_trades': len(trades)
    }
    return results

# executor (paper / live)
class SimpleExecutor:
    def __init__(self, exchange, cfg):
        self.ex = exchange
        self.cfg = cfg
        self.positions = []
        self.log_file = "trades_log.csv"
        if not os.path.exists(self.log_file):
            with open(self.log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['time','symbol','side','price','qty','type','status','note'])

    def place_order(self, symbol, side, price, qty, order_type='market'):
        ts = datetime.utcnow().isoformat()
        if self.cfg['paper_mode']:
            # simulate fill
            status = 'closed'
            with open(self.log_file, 'a') as f:
                writer = csv.writer(f)
                writer.writerow([ts,symbol,side,price,qty,order_type,status,'paper'])
            print(f"[PAPER] {side} {qty} {symbol} @ {price}")
            return {'status': 'closed', 'price': price, 'qty': qty}
        else:
            # real trading via ccxt
            try:
                if order_type=='market':
                    order = self.ex.create_market_buy_order(symbol, qty) if side.lower()=='buy' else self.ex.create_market_sell_order(symbol, qty)
                else:
                    order = self.ex.create_order(symbol, 'limit', side, qty, price)
                with open(self.log_file, 'a') as f:
                    writer = csv.writer(f)
                    writer.writerow([ts,symbol,side,price,qty,order_type,order['status'],'live'])
                return order
            except Exception as e:
                print("Order error:",e)
                return None

# live loop (polling)
def live_loop(cfg):
    ex = init_exchange(cfg)
    execr = SimpleExecutor(ex, cfg)

    print("🚀 Starting live loop | paper_mode =", cfg['paper_mode'])

    balance = cfg['balance_usdt']
    trades = []

    # ✅ TEMP: ONE TEST TRADE TO VERIFY UI (REMOVE LATER)
    trade = execr.place_order(
        cfg['symbol'],
        'buy',
        30000,      # dummy price for paper mode
        0.001
    )

    trades.append({
        "side": "buy",
        "price": 30000,
        "qty": 0.001,
        "pnl": 0
    })

    write_stats(balance, trades)

    while True:
        try:
            df = fetch_ohlcv(ex, cfg['symbol'], cfg['timeframe'], limit=200)
            df = generate_signals(df, cfg)
            last = df.iloc[-1]

            if last['long_entry']:
                usd = balance * cfg['order_size_pct']
                qty = usd / last['close']

                entry_price = float(last['close'])
                sl_price = entry_price * (1 - cfg['sl_pct'] / 100)
                tp_price = entry_price * (1 + cfg['tp_pct'] / 100)

                print(f"📈 Signal BUY @ {entry_price}")

                trade = execr.place_order(
                    cfg['symbol'],
                    'buy',
                    entry_price,
                    qty
                )

                # ✅ simulate immediate TP hit (for MVP stats)
                exit_price = tp_price
                pnl = (exit_price - entry_price) * qty

                balance += pnl

                trades.append({
                    "side": "buy",
                    "entry": entry_price,
                    "exit": exit_price,
                    "qty": round(qty, 6),
                    "pnl": round(pnl, 2)
                })

                write_stats(balance, trades)

                print(f"✅ Trade closed | PnL: {round(pnl, 2)} | Balance: {round(balance, 2)}")

                time.sleep(5)  # avoid overtrading

            time.sleep(10)

        except Exception as e:
            print("❌ Live loop error:", e)
            time.sleep(5)

# ----- CLI -----
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", action='store_true')
    parser.add_argument("--paper", action='store_true')
    parser.add_argument("--live", action='store_true')
    args = parser.parse_args()
    cfg = CONFIG.copy()
    cfg['paper_mode'] = True
    if args.live:
        cfg['paper_mode'] = False
    ex = init_exchange(cfg)
    if args.backtest:
        limit = min(1000, int(cfg['since_minutes']*60 / (60)))  # crude limit
        df = fetch_ohlcv(ex, cfg['symbol'], cfg['timeframe'], limit=1000)
        df = generate_signals(df, cfg)
        res = backtest(df, cfg, verbose=True)
        print("Backtest summary:", res['num_trades'], "trades total_pnl", res['total_pnl'], "win_rate", res['win_rate'])
    elif args.paper or args.live:
        if args.live and cfg['paper_mode']==False and (not cfg['api_key'] or not cfg['api_secret']):
            print("For LIVE mode set api_key and api_secret in CONFIG. Exiting.")
            return
        # set exchange keys
        ex.apiKey = cfg['api_key']
        ex.secret = cfg['api_secret']
        if args.paper:
            cfg['paper_mode']=True
        else:
            cfg['paper_mode']=False
        live_loop(cfg)
    else:
        print("Use --backtest, --paper or --live")

if __name__ == '__main__':
    main()
