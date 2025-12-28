# backtest.py
"""
Advanced candle-aware backtester (Option B)
- simulates entry at next candle open with slippage
- checks SL/TP inside candles using high/low
- heuristic to resolve same-candle both-hit ambiguity
- outputs JSON + CSV with trades, equity curve, daily pnl
"""

import ccxt
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timezone, timedelta
import math

START_UTC = "2024-01-01T00:00:00Z"   # 1 year backtest window
LIMIT = 1000                         # per-request fetch size
CACHE_DIR = "ohlcv_cache"


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(BASE_DIR, "backtest_results.json")
OUT_TRADES_CSV = os.path.join(BASE_DIR, "backtest_trades.csv")


# ---------- Config ----------
EXCHANGE_ID = "binance"
SYMBOL = "BTC/USDT"               # change as needed or pass via env
TIMEFRAME = "5m"                  # 1m, 5m, 1h, 1d
START_UTC = None                  # e.g. "2024-01-01T00:00:00Z" or None for max available
LIMIT = 10000                     # OHLCV candles to fetch (ccxt limit may apply)
CACHE_DIR = "ohlcv_cache"
OUT_JSON = "backtest_results.json"
OUT_TRADES_CSV = "backtest_trades.csv"

# Strategy params (match your live settings)
EMA_FAST = 8
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_MIN = 40
RSI_MAX = 70
SIZE_PCT = 25.0   # % of FREE equity per trade (same as live)
SL_PCT = 0.6      # stop-loss percent (e.g. 0.6% below entry)
TP_PCT = 1.2      # take-profit percent
ATR_PERIOD = 14
ATR_SL_MULT = 1.2      # stop = 1.2 × ATR
ATR_TP_MULT = 1.6      # target = 1.6 × ATR (positive expectancy)

# --- Trade management ---
BREAKEVEN_R = 1.0   # move SL to entry after +0.5R

# ---- TRAILING STOP CONFIG ----
TRAIL_ATR_MULT = 1.2     # distance = ATR * multiplier

# ---- PARTIAL EXIT CONFIG ----
PARTIAL_EXIT_R = 1.0        # take partial at +1R
PARTIAL_EXIT_PCT = 0.5     # close 50% position

# ---- TIME EXIT ----
MAX_BARS_IN_TRADE = 18   # adjust per timeframe

# --- Stop-loss control ---
SL_DELAY_CANDLES = 2   # ignore SL for first N candles after entry

# -------- STRATEGY GUARDS --------
EMA_TREND = 200           # Trend filter
COOLDOWN_BARS = 30        # No re-entry after exit
MAX_TRADES_PER_DAY = 3    # Anti overtrading
MIN_RANGE_PCT = 0.08      # Volatility filter (%)

# Execution model
COMMISSION_PCT = 0.001   # 0.1% spot taker fee
SLIPPAGE_PCT = 0.001     # 0.1% slippage (entry/exit)

# Backtest settings
INITIAL_BALANCE = 1000.0
MIN_USD_TRADE = 10.0
# Risk-based position sizing
RISK_PCT = 1.0        # % of equity risked per trade (1% = professional safe default)
MAX_USD_CAP = 200   # Optional cap (e.g. 200), or keep None


# Misc
VERBOSE = True

# ---------- Helpers ----------
def safe(x):
    try:
        x = float(x)
        if math.isnan(x) or math.isinf(x):
            return 0.0
        return x
    except:
        return 0.0
        
from datetime import datetime as _dt

def load_ohlcv(
    symbol=SYMBOL,
    timeframe=TIMEFRAME,
    limit=LIMIT,
    cache_dir=CACHE_DIR,
    max_candles=50,   # ⭐ 1 YEAR of 1m candles (~525k)
):

    """
    Load OHLCV with caching. If cache missing or stale, fetch from Binance with pagination.
    - symbol: "BTC/USDT"
    - timeframe: "1m","5m","15m","1h",...
    - limit: per-request limit (ccxt often caps at 1000)
    - max_candles: total candles to fetch if no START_UTC (safety cap)
    """

    os.makedirs(cache_dir, exist_ok=True)
    fname = f"{cache_dir}/{symbol.replace('/', '_')}_{timeframe}.csv"

    # ----------------------------
    # Helper: parse ts cell to datetime
    # ----------------------------
    def _to_dt_series(s):
        # if integer ms
        if pd.api.types.is_integer_dtype(s) or pd.api.types.is_float_dtype(s):
            return pd.to_datetime(s, unit="ms", utc=True)
        # if string ISO
        return pd.to_datetime(s, utc=True)

    # ----------------------------
    # If cache exists, try to load
    # ----------------------------
    if os.path.exists(fname):
        try:
            df = pd.read_csv(fname)
            # normalize ts column to datetime
            df["ts"] = _to_dt_series(df["ts"])
            # basic sanity: if last cached ts is in future by > 2 days, consider cache corrupt
            now = _dt.now(timezone.utc)
            last_ts = df["ts"].iloc[-1]
            if last_ts > (now + pd.Timedelta(days=2)):
                print("🔥 Cache timestamp is far in future — deleting cache:", fname)
                os.remove(fname)
            else:
                print("Using cached OHLCV:", fname)
                return df.set_index("ts")
        except Exception as e:
            print("Cache load failed, deleting and refetching:", e)
            try:
                os.remove(fname)
            except:
                pass

    # ----------------------------
    # If we reach here: fetch from Binance (with pagination)
    # ----------------------------
    print("Fetching OHLCV from Binance with pagination…")
    ex = ccxt.binance({"enableRateLimit": True})

    # ccxt timeframe to ms multiplier isn't needed here — use since param
    # default per-request limit: use min(limit, 1000) to be safe
    per_request = min(1000, int(limit))

    all_rows = []
    fetched = 0

    # determine since: if START_UTC set, fetch from that timestamp, else fetch most recent max_candles
    if START_UTC:
        since_ts = int(pd.to_datetime(START_UTC).tz_convert("UTC").view("int64") // 10**6)  # ms
        # ccxt expects integer ms since epoch
        # we'll walk forwards from since_ts
        forward = True
    else:
        # fetch latest candles by iterating backwards: fetch most recent `per_request`, then set since to earliest_ms - 1 and fetch earlier, etc.
        # easier approach: fetch newest batch, prepend earlier batches by requesting with "since" of earliest - (per_request * timeframe_ms)
        # We'll fetch forward by requesting since = now - (per_request * timeframe_ms * n_batches)
        # Simpler: fetch most recent `per_request` and then iterate using 'since' earlier timestamps.
        # Start by fetching latest batch (no since) and then use earliest - 1 as new "end" marker to fetch earlier candles.
        since_ts = None
        forward = False

    # helper to convert timeframe string to milliseconds approx (for stepping)
    def timeframe_to_ms(tf):
        # supports "1m","5m","15m","1h","4h","1d"
        if tf.endswith("m"):
            return int(tf[:-1]) * 60_000
        if tf.endswith("h"):
            return int(tf[:-1]) * 3_600_000
        if tf.endswith("d"):
            return int(tf[:-1]) * 86_400_000
        return 60_000

    tf_ms = timeframe_to_ms(timeframe)

    # Pagination loop
    try:
        if forward:
            # fetch forward from since_ts until latest
            cur_since = since_ts
            while True:
                batch = ex.fetch_ohlcv(symbol, timeframe, since=cur_since, limit=per_request)
                if not batch:
                    break
                all_rows.extend(batch)
                fetched += len(batch)
                cur_since = batch[-1][0] + 1  # next ms after last fetched candle
                if fetched >= max_candles:
                    break
                # if we received fewer than requested, probably reached latest
                if len(batch) < per_request:
                    break
        else:
            # fetch latest batch first (no since) to get recent candles
            batch = ex.fetch_ohlcv(symbol, timeframe, limit=per_request)
            if not batch:
                raise RuntimeError("No OHLCV returned")
            all_rows.extend(batch)
            fetched += len(batch)
            # now iterate backwards: request earlier batches by using "since" equal to earliest_ms - (per_request * tf_ms)
            while fetched < max_candles:
                earliest_ms = all_rows[0][0]
                target_since = max(0, earliest_ms - per_request * tf_ms - 1)
                prev_batch = ex.fetch_ohlcv(symbol, timeframe, since=target_since, limit=per_request)
                if not prev_batch:
                    break
                # prev_batch may overlap; ensure we prepend only earlier ones
                # filter out candles >= earliest_ms
                prepend = [b for b in prev_batch if b[0] < earliest_ms]
                if not prepend:
                    break
                all_rows = prepend + all_rows
                fetched = len(all_rows)
                if len(prev_batch) < per_request:
                    break
    except Exception as e:
        print("OHLCV fetch error:", e)
        # fallback: try single fetch without pagination
        try:
            data = ex.fetch_ohlcv(symbol, timeframe, limit=per_request)
            all_rows = data
        except Exception as e2:
            raise

    # Build DataFrame
    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)

    # Optionally trim to START_UTC if provided (keep only ts >= START_UTC)
    if START_UTC:
        start_dt = pd.to_datetime(START_UTC).tz_convert("UTC")
        df = df[df["ts"] >= start_dt]

    # Save cache and return
    df.to_csv(fname, index=False)
    print("Saved OHLCV to cache:", fname)
    print("DEBUG (BINANCE) OHLCV HEAD:\n", df.head())
    print("DEBUG (BINANCE) OHLCV TAIL:\n", df.tail())
    return df.set_index("ts")



def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(series, n=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(alpha=1 / n, adjust=False).mean()
    ma_down = down.ewm(alpha=1 / n, adjust=False).mean()
    rs = ma_up / (ma_down + 1e-9)
    return 100 - (100 / (1 + rs))


def simulate_entry(exec_price, usd_amount, commission_pct=COMMISSION_PCT):
    # qty before fees
    qty = safe(usd_amount / exec_price) if exec_price > 0 else 0.0
    used = qty * exec_price
    fee = used * commission_pct
    # For spot, fee charged in quote (USDT) — we reduce net used accordingly for simulation reporting
    net_used = used + fee
    return {"exec_price": exec_price, "qty": qty, "used_usd": used, "fee_usd": fee, "net_used_usd": net_used}

def simulate_exit(exec_price, qty, commission_pct=COMMISSION_PCT):
    used = qty * exec_price
    fee = used * commission_pct
    net_proceed = used - fee
    return {"exec_price": exec_price, "qty": qty, "used_usd": used, "fee_usd": fee, "net_proceed_usd": net_proceed}

def atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()

    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)

    return true_range.ewm(alpha=1 / period, adjust=False).mean()


# ---------- Backtest engine (candle-aware) ----------
def run_backtest(symbol=SYMBOL, timeframe=TIMEFRAME, start_utc=START_UTC, limit=LIMIT):
    df = load_ohlcv(symbol, timeframe, limit=limit)
    if start_utc:
        df = df[df.index >= pd.to_datetime(start_utc).tz_convert("UTC")]

    # compute indicators
    df["ema_fast"] = ema(df["close"], EMA_FAST)
    df["ema_slow"] = ema(df["close"], EMA_SLOW)
    df["rsi"] = rsi(df["close"], RSI_PERIOD)
    df["ema_trend"] = ema(df["close"], EMA_TREND)
    df["atr"] = atr(df, ATR_PERIOD)



    # we iterate row by row and use next bar's open as entry price to avoid lookahead
    timestamps = df.index
    equity = INITIAL_BALANCE
    free = equity
    open_pos = None  # dict with keys: entry_price, qty, used_usd, fee_usd, sl, tp, entry_ts
    trades = []
    equity_curve = []
    daily_pnl = {}
    last_exit_index = {}
    trades_today = {}

    def record_daily_pnl(ts, pnl):
        day = ts.date().isoformat()
        daily_pnl.setdefault(day, 0.0)
        daily_pnl[day] += pnl

    for i in range(len(df) - 1):  # last candle has no next open for entry
        row = df.iloc[i]
        t = df.index[i]
        next_bar = df.iloc[i + 1]
        next_open = safe(next_bar["open"])

        # update equity curve (mark-to-market)
        mtm = 0.0
        if open_pos:
            # mark to market with current close
            mtm = (safe(df.iloc[i]["close"]) - open_pos["entry_price"]) * open_pos["qty"]
        equity_curve.append({"ts": t.isoformat(), "equity": equity + mtm})

        # If we have open position, check SL/TP inside current candle (using this candle's high/low)
        if open_pos:
            high = safe(row["high"])
            low = safe(row["low"])
            if not open_pos.get("breakeven_done", False):
                move = high - open_pos["entry_price"]
                if move >= BREAKEVEN_R * open_pos["risk_per_unit"]:
                    open_pos["sl"] = open_pos["entry_price"]
                    open_pos["breakeven_done"] = True
                    if VERBOSE:
                        print(f"BREAKEVEN @ {t}")

            # -----------------------------
            # PARTIAL EXIT AT +1R
            # -----------------------------
            if not open_pos.get("partial_done", False):
                r = open_pos["risk_per_unit"]
                if r > 0 and high >= open_pos["entry_price"] + PARTIAL_EXIT_R * r:
                    close_qty = open_pos["qty"] * PARTIAL_EXIT_PCT
            
                    exit_price = open_pos["entry_price"] + PARTIAL_EXIT_R * r
                    res = simulate_exit(exit_price, close_qty)
            
                    pnl = safe(
                        (res["exec_price"] - open_pos["entry_price"]) * close_qty
                        - res["fee_usd"]
                    )
            
                    equity += pnl
                    record_daily_pnl(t, pnl)
            
                    trades.append({
                        "entry_ts": open_pos["entry_ts"].isoformat(),
                        "exit_ts": t.isoformat(),
                        "symbol": symbol,
                        "entry_price": open_pos["entry_price"],
                        "exit_price": res["exec_price"],
                        "qty": close_qty,
                        "pnl": pnl,
                        "fee": res["fee_usd"],
                        "type": "PARTIAL_1R",
                    })
            
                    open_pos["qty"] -= close_qty
                    open_pos["partial_done"] = True
            
                    if VERBOSE:
                        print(f"PARTIAL EXIT @ +1R → {res['exec_price']:.2f}")


            # -----------------------------
            # TRAILING STOP (ATR-based)
            # Only after breakeven
            # -----------------------------
            if open_pos.get("breakeven_done", False):
                atr_val = safe(row["atr"])
                if atr_val > 0:
                    trail_sl = safe(row["close"] - TRAIL_ATR_MULT * atr_val)
            
                    # move SL only forward
                    if trail_sl > open_pos["sl"]:
                        open_pos["sl"] = trail_sl
                        if VERBOSE:
                            print(f"TRAIL SL → {trail_sl:.2f} @ {t}")

            
            # -----------------------------
            # TIME-BASED EXIT
            # -----------------------------
            bars_in_trade = i - open_pos["entry_index"]
            if bars_in_trade >= MAX_BARS_IN_TRADE:
                exit_price = safe(row["close"])
                res = simulate_exit(exit_price, open_pos["qty"])
            
                pnl = safe(
                    (res["exec_price"] - open_pos["entry_price"]) * open_pos["qty"]
                    - res["fee_usd"]
                )
            
                equity += pnl
                record_daily_pnl(t, pnl)
            
                trades.append({
                    "entry_ts": open_pos["entry_ts"].isoformat(),
                    "exit_ts": t.isoformat(),
                    "symbol": symbol,
                    "entry_price": open_pos["entry_price"],
                    "exit_price": res["exec_price"],
                    "qty": open_pos["qty"],
                    "pnl": pnl,
                    "fee": res["fee_usd"],
                    "type": "TIME_EXIT",
                })

                last_exit_index[symbol] = i
            
                if VERBOSE:
                    print(f"TIME EXIT @ {t}")
            
                open_pos = None
                continue



            sl_allowed = (i - open_pos["entry_index"]) >= SL_DELAY_CANDLES

            hit_tp = high >= open_pos["tp"] if open_pos.get("tp", 0) > 0 else False
            hit_sl = (
                low <= open_pos["sl"]
                if sl_allowed and open_pos.get("sl", 0) > 0
                else False
            )

            if hit_tp and not hit_sl:
                # TP hit this candle; assume exit at TP price (no extra slippage inside candle)
                exit_price = open_pos["tp"]
                res = simulate_exit(exit_price, open_pos["qty"])
                pnl = safe((res["exec_price"] - open_pos["entry_price"]) * open_pos["qty"] - res["fee_usd"])
                equity += pnl
                record_daily_pnl(t, pnl)
                trades.append({
                    "entry_ts": open_pos["entry_ts"].isoformat(),
                    "exit_ts": t.isoformat(),
                    "symbol": symbol,
                    "entry_price": open_pos["entry_price"],
                    "exit_price": res["exec_price"],
                    "qty": open_pos["qty"],
                    "pnl": pnl,
                    "fee": res["fee_usd"],
                    "type": "TP",
                })
                last_exit_index[symbol] = i
                open_pos = None
                continue

            if hit_sl and not hit_tp:
                exit_price = open_pos["sl"]
                res = simulate_exit(exit_price, open_pos["qty"])
                pnl = safe((res["exec_price"] - open_pos["entry_price"]) * open_pos["qty"] - res["fee_usd"])
                equity += pnl
                record_daily_pnl(t, pnl)
                trades.append({
                    "entry_ts": open_pos["entry_ts"].isoformat(),
                    "exit_ts": t.isoformat(),
                    "symbol": symbol,
                    "entry_price": open_pos["entry_price"],
                    "exit_price": res["exec_price"],
                    "qty": open_pos["qty"],
                    "pnl": pnl,
                    "fee": res["fee_usd"],
                    "type": "SL",
                })
                last_exit_index[symbol] = i
                open_pos = None
                continue

            if hit_tp and hit_sl:
                # ambiguous: both hit in same candle. use heuristic: whichever is closer to entry gets hit first.
                dist_tp = abs(open_pos["tp"] - open_pos["entry_price"])
                dist_sl = abs(open_pos["entry_price"] - open_pos["sl"])
                if dist_tp <= dist_sl:
                    exit_price = open_pos["tp"]
                    res = simulate_exit(exit_price, open_pos["qty"])
                    pnl = safe((res["exec_price"] - open_pos["entry_price"]) * open_pos["qty"] - res["fee_usd"])
                    equity += pnl
                    record_daily_pnl(t, pnl)
                    trades.append({
                        "entry_ts": open_pos["entry_ts"].isoformat(),
                        "exit_ts": t.isoformat(),
                        "symbol": symbol,
                        "entry_price": open_pos["entry_price"],
                        "exit_price": res["exec_price"],
                        "qty": open_pos["qty"],
                        "pnl": pnl,
                        "fee": res["fee_usd"],
                        "type": "TP(same-candle)",
                    })
                    last_exit_index[symbol] = i
                    open_pos = None
                    continue
                else:
                    exit_price = open_pos["sl"]
                    res = simulate_exit(exit_price, open_pos["qty"])
                    pnl = safe((res["exec_price"] - open_pos["entry_price"]) * open_pos["qty"] - res["fee_usd"])
                    equity += pnl
                    record_daily_pnl(t, pnl)
                    trades.append({
                        "entry_ts": open_pos["entry_ts"].isoformat(),
                        "exit_ts": t.isoformat(),
                        "symbol": symbol,
                        "entry_price": open_pos["entry_price"],
                        "exit_price": res["exec_price"],
                        "qty": open_pos["qty"],
                        "pnl": pnl,
                        "fee": res["fee_usd"],
                        "type": "SL(same-candle)",
                    })
                    last_exit_index[symbol] = i
                    open_pos = None
                    continue

            # else not hit, continue and keep position open

        # If no position, evaluate entry signal using indicators up to current candle
        if not open_pos:

            if i == 0:
                continue
            ema_fast = safe(row.get("ema_fast", math.nan))
            ema_slow = safe(row.get("ema_slow", math.nan))
            ema_trend = safe(row.get("ema_trend", math.nan))
            rsi_val = safe(row.get("rsi", math.nan))
            atr_val = safe(row.get("atr", math.nan))

            if any(math.isnan(x) for x in [ema_fast, ema_slow, ema_trend, rsi_val, atr_val]):
                continue

            trend_ok = (
                row["close"] > row["ema_trend"] and
                row["ema_fast"] > row["ema_slow"]
            )

            momentum_ok = (
                RSI_MIN < row["rsi"] < RSI_MAX and
                row["rsi"] > df.iloc[i - 1]["rsi"]
            )

            vol_ok = row["atr"] > df["atr"].rolling(50).mean().iloc[i]

            long_signal = trend_ok and momentum_ok and vol_ok

            # -------- ENTRY FILTERS (PHASE A) --------

            # cooldown protection
            if symbol in last_exit_index:
                if i - last_exit_index[symbol] < COOLDOWN_BARS:
                    continue

            # daily trade limit
            day = t.date().isoformat()
            if trades_today.get(day, 0) >= MAX_TRADES_PER_DAY:
                continue



            if long_signal:
                entry_price = safe(next_open * (1 + SLIPPAGE_PCT))
               
                atr_val = safe(row["atr"])
                if atr_val <= 0:
                    continue
                
                sl_price = safe(entry_price - ATR_SL_MULT * atr_val)
                tp_price = safe(entry_price + ATR_TP_MULT * atr_val)

                # record open position (entry_ts = next bar ts)
                risk_usd = safe(equity * (RISK_PCT / 100.0))
                risk_per_unit = abs(entry_price - sl_price)
                if risk_per_unit <= 0:
                    continue

                qty_by_risk = safe(risk_usd / risk_per_unit)
                qty_by_cap = safe(equity / entry_price)

                qty = min(qty_by_risk, qty_by_cap)
                usd_size = safe(qty * entry_price)

                if MAX_USD_CAP is not None:
                    usd_size = min(usd_size, MAX_USD_CAP)
                    qty = safe(usd_size / entry_price)

                if usd_size < MIN_USD_TRADE:
                    if VERBOSE:
                        print("skipping trade: min trade size")
                    continue

                entry_exec = simulate_entry(entry_price, usd_size)

                open_pos = {
                    "entry_ts": next_bar.name,  # timestamp
                    "entry_index": i + 1,
                    "entry_price": entry_exec["exec_price"],
                    "qty": qty,
                    "used_usd": entry_exec["used_usd"],
                    "fee_usd": entry_exec["fee_usd"],
                    "sl": sl_price,
                    "tp": tp_price,
                    "risk_per_unit": risk_per_unit,
                    "breakeven_done": False,
                    "partial_done": False,
                }
              
                if VERBOSE: 
                    print(
                        f"ENTER {next_bar.name} {symbol} "
                        f"@ {entry_exec['exec_price']} qty={qty:.6f}"
                        )
             

    # end loop
    # add final mtm point
    last_ts = df.index[-1]
    if open_pos:
        mtm = (safe(df.iloc[-1]["close"]) - open_pos["entry_price"]) * open_pos["qty"]
    else:
        mtm = 0.0
    equity_curve.append({"ts": last_ts.isoformat(), "equity": equity + mtm})

    # compute metrics
    equity_series = [p["equity"] for p in equity_curve]
    returns = []
    for i in range(1, len(equity_series)):
        prev = equity_series[i - 1]
        cur = equity_series[i]
        ret = (cur - prev) / max(prev, 1e-9)
        returns.append(ret)
    total_return = (equity_series[-1] - INITIAL_BALANCE) / INITIAL_BALANCE
    total_pnl = equity_series[-1] - INITIAL_BALANCE
    win_trades = [t for t in trades if t["pnl"] > 0]
    loss_trades = [t for t in trades if t["pnl"] < 0]
    win_rate = len(win_trades) / len(trades) * 100 if trades else 0.0
    profit_factor = (sum(t["pnl"] for t in win_trades) / abs(sum(t["pnl"] for t in loss_trades))) if loss_trades else float("inf")
    # max drawdown
    peak = -float("inf")
    max_dd = 0.0
    peak = equity_series[0]
    peak_ts = equity_curve[0]["ts"]
    dd_series = []
    for p in equity_curve:
        if p["equity"] > peak:
            peak = p["equity"]
            peak_ts = p["ts"]
        dd = (peak - p["equity"]) / max(peak, 1e-9)
        dd_series.append({"ts": p["ts"], "dd": dd})
        if dd > max_dd:
            max_dd = dd

    results = {
        "symbol": symbol,
        "timeframe": timeframe,
        "initial_balance": INITIAL_BALANCE,
        "final_equity": equity_series[-1],
        "total_return": total_return,
        "total_pnl": total_pnl,
        "n_trades": len(trades),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd,
        "equity_curve": equity_curve,
        "drawdown_series": dd_series,
        "daily_pnl": daily_pnl,
        "trades": trades,
        "params": {
            "ema_fast": EMA_FAST,
            "ema_slow": EMA_SLOW,
            "rsi_period": RSI_PERIOD,
            "rsi_filter": [RSI_MIN, RSI_MAX],
            "size_pct": SIZE_PCT,
            "sl_pct": SL_PCT,
            "tp_pct": TP_PCT,
            "commission_pct": COMMISSION_PCT,
            "slippage_pct": SLIPPAGE_PCT,
        }
    }

    # save outputs
    with open(OUT_JSON, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # trades CSV
    if trades:
        trades_df = pd.DataFrame(trades)
        trades_df.to_csv(OUT_TRADES_CSV, index=False)
    print("Backtest complete:", OUT_JSON, OUT_TRADES_CSV)
    print("Summary:", {
        "final_equity": results["final_equity"],
        "n_trades": results["n_trades"],
        "win_rate": results["win_rate"],
        "profit_factor": results["profit_factor"],
        "max_drawdown": results["max_drawdown"],
    })
    return results

if __name__ == "__main__":
    res = run_backtest()

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--symbol", type=str, default=SYMBOL)
    parser.add_argument("--timeframe", type=str, default=TIMEFRAME)
    parser.add_argument("--ema_fast", type=int, default=EMA_FAST)
    parser.add_argument("--ema_slow", type=int, default=EMA_SLOW)
    parser.add_argument("--rsi_period", type=int, default=RSI_PERIOD)
    parser.add_argument("--sl_pct", type=float, default=SL_PCT)
    parser.add_argument("--tp_pct", type=float, default=TP_PCT)
    parser.add_argument("--size_pct", type=float, default=SIZE_PCT)

    args = parser.parse_args()

    EMA_FAST = args.ema_fast
    EMA_SLOW = args.ema_slow
    RSI_PERIOD = args.rsi_period
    SL_PCT = args.sl_pct
    TP_PCT = args.tp_pct
    SIZE_PCT = args.size_pct

    run_backtest(
        symbol=args.symbol,
        timeframe=args.timeframe,
    )

