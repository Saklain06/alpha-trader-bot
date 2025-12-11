from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import json
import os
import ccxt
import uuid
import math
import asyncio
from datetime import datetime, timezone

# ------------------------
# CONFIG
# ------------------------
AUTO_TRADING_ENABLED = False  # default OFF

MIN_CLOSE_QTY_PCT = 0.15  # 15% of position for dust auto-close

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]

TRADES_FILE = "trades_log.csv"
STATS_FILE = "stats.json"
BASE_BALANCE = 1000.0

# Auto strategy
AUTO_STRATEGY_ENABLED = True
STRATEGY_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]
STRATEGY_TIMEFRAME = "1m"
STRATEGY_SIZE_PCT = 25.0  # % of FREE equity
EMA_FAST = 8
EMA_SLOW = 21
RSI_PERIOD = 14

WATCHER_INTERVAL = 5
STRATEGY_INTERVAL = 30

# ------------------------
# APP
# ------------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------
# UTILS
# ------------------------
def safe(val):
    try:
        val = float(val)
        if math.isnan(val) or math.isinf(val):
            return 0.0
        return round(val, 6)
    except Exception:
        return 0.0


def num(val):
    try:
        if val in [None, "", "nan"]:
            return 0.0
        val = float(val)
        if math.isnan(val) or math.isinf(val):
            return 0.0
        return round(val, 6)
    except Exception:
        return 0.0


def ensure_trades_df():
    """Create or normalize trades dataframe with all required columns."""
    cols = [
        "id",
        "time",
        "symbol",
        "side",
        "entry_price",
        "qty",
        "used_usd",
        "status",
        "pnl",
        "sl",
        "tp",
        "exit_price",
        "current_price",
        "unrealized_pnl",
    ]

    if not os.path.exists(TRADES_FILE):
        return pd.DataFrame(columns=cols)

    df = pd.read_csv(TRADES_FILE)

    for c in cols:
        if c not in df.columns:
            df[c] = "" if c in ["id", "time", "symbol", "side", "status"] else 0.0

    return df[cols]


# ------------------------
# ACCOUNTING
# ------------------------
def get_equity_locked_free():
    equity = BASE_BALANCE
    locked = 0.0

    df = ensure_trades_df()
    if df.empty:
        return safe(equity), 0.0, safe(equity)

    closed = df[df["status"] == "closed"]
    if not closed.empty:
        equity += num(closed["pnl"].sum())

    open_df = df[df["status"] == "open"]
    for _, r in open_df.iterrows():
        locked += num(r["used_usd"])
        equity += num(r.get("unrealized_pnl", 0))

    free = safe(equity - locked)
    return safe(equity), safe(locked), safe(free)


def update_stats():
    equity, locked, free = get_equity_locked_free()

    stats = {
        "balance": equity,
        "locked": locked,
        "free": free,
        "mode": "auto" if AUTO_TRADING_ENABLED else "manual",
        "total_trades": 0,
        "total_pnl": 0.0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
    }

    df = ensure_trades_df()
    if df.empty:
        json.dump(stats, open(STATS_FILE, "w"), indent=2)
        return

    stats["total_trades"] = len(df)

    closed = df[df["status"] == "closed"]
    if closed.empty:
        json.dump(stats, open(STATS_FILE, "w"), indent=2)
        return

    wins = closed[closed["pnl"] > 0]
    losses = closed[closed["pnl"] < 0]

    stats["total_pnl"] = num(closed["pnl"].sum())
    stats["win_rate"] = safe(len(wins) / len(closed) * 100) if len(closed) else 0.0

    if not losses.empty:
        stats["profit_factor"] = safe(
            wins["pnl"].sum() / abs(losses["pnl"].sum())
        )

    json.dump(stats, open(STATS_FILE, "w"), indent=2)


# ------------------------
# BASIC API
# ------------------------
@app.get("/stats")
def stats():
    update_stats()
    return json.load(open(STATS_FILE))


@app.get("/trades")
def trades():
    df = ensure_trades_df()
    if df.empty:
        return []
    return df.fillna("").tail(50).to_dict("records")


@app.get("/positions")
def positions():
    df = ensure_trades_df()
    if df.empty:
        return []
    return df[df["status"] == "open"].fillna("").to_dict("records")


# ------------------------
# TRADE MODE TOGGLE
# ------------------------
@app.post("/trade-mode")
def set_trade_mode(mode: str = Query(...)):
    global AUTO_TRADING_ENABLED

    if mode not in ["manual", "auto"]:
        return {"error": "Invalid mode"}

    AUTO_TRADING_ENABLED = mode == "auto"

    return {
        "mode": mode,
        "auto_trading": AUTO_TRADING_ENABLED,
    }


# ------------------------
# PRICE WATCHER + SL/TP
# ------------------------
def refresh_prices():
    df = ensure_trades_df()
    if df.empty:
        return

    ex = ccxt.bingx({"enableRateLimit": True})

    for i, r in df.iterrows():
        if r["status"] != "open":
            continue

        try:
            price = num(ex.fetch_ticker(r["symbol"])["last"])
        except Exception:
            continue

        qty = num(r["qty"])
        entry = num(r["entry_price"])

        unreal = num((price - entry) * qty)
        df.at[i, "current_price"] = price
        df.at[i, "unrealized_pnl"] = unreal

        sl = num(r.get("sl"))
        tp = num(r.get("tp"))

        # TP first
        if tp > 0 and price >= tp:
            df.at[i, "exit_price"] = price
            df.at[i, "pnl"] = unreal
            df.at[i, "status"] = "closed"
            continue

        # SL
        if sl > 0 and price <= sl:
            df.at[i, "exit_price"] = price
            df.at[i, "pnl"] = unreal
            df.at[i, "status"] = "closed"
            continue

    df.to_csv(TRADES_FILE, index=False)
    update_stats()


# ------------------------
# PAPER BUY (NET POSITION PER SYMBOL)
# ------------------------
@app.post("/paper-buy")
def paper_buy(
    symbol: str = Query("BTC/USDT"),
    size_pct: float = Query(10.0),
    sl_pct: float = Query(1.0),
    tp_pct: float = Query(2.0),
):
    if symbol not in SYMBOLS:
        return {"error": "Invalid symbol"}

    equity, locked, free = get_equity_locked_free()
    usd_to_use = safe(equity * (size_pct / 100))

    if usd_to_use < 5:
        return {"error": "Trade too small"}

    ex = ccxt.bingx({"enableRateLimit": True})
    price = num(ex.fetch_ticker(symbol)["last"])

    qty = safe(usd_to_use / price)
    used_usd = safe(qty * price)

    # final clamp
    if used_usd > free:
        qty = safe(free / price)
        used_usd = safe(qty * price)

    if used_usd <= 0:
        return {"error": "Insufficient free balance"}

    sl = safe(price * (1 - sl_pct / 100)) if sl_pct > 0 else 0.0
    tp = safe(price * (1 + tp_pct / 100)) if tp_pct > 0 else 0.0

    df = ensure_trades_df()

    # netting: if same symbol open -> add to it
    existing = df[(df["status"] == "open") & (df["symbol"] == symbol)]

    if not existing.empty:
        idx = existing.index[0]

        old_qty = num(df.at[idx, "qty"])
        old_price = num(df.at[idx, "entry_price"])
        old_used = num(df.at[idx, "used_usd"])

        total_qty = safe(old_qty + qty)
        total_used = safe(old_used + used_usd)
        avg_price = safe((old_qty * old_price + qty * price) / total_qty)

        df.at[idx, "qty"] = total_qty
        df.at[idx, "used_usd"] = total_used
        df.at[idx, "entry_price"] = avg_price

        df.to_csv(TRADES_FILE, index=False)
        update_stats()

        return {
            "status": "added",
            "symbol": symbol,
            "avg_entry_price": avg_price,
            "total_qty": total_qty,
            "total_used": total_used,
        }

    # else: create new trade
    trade = {
        "id": str(uuid.uuid4()),
        "time": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "side": "buy",
        "entry_price": price,
        "qty": qty,
        "used_usd": used_usd,
        "status": "open",
        "pnl": 0.0,
        "sl": sl,
        "tp": tp,
        "exit_price": 0.0,
        "current_price": price,
        "unrealized_pnl": 0.0,
    }

    df = pd.concat([df, pd.DataFrame([trade])], ignore_index=True)
    df.to_csv(TRADES_FILE, index=False)
    update_stats()
    return trade


# ------------------------
# UPDATE SL / TP (with immediate check)
# ------------------------
@app.post("/update-sl-tp")
def update_sl_tp(
    trade_id: str = Query(...),
    sl: float = Query(0.0),
    tp: float = Query(0.0),
):
    df = ensure_trades_df()
    mask = (df["id"] == trade_id) & (df["status"] == "open")
    if not mask.any():
        return {"error": "No open trade with this ID"}

    idx = df[mask].index[0]

    df.at[idx, "sl"] = num(sl)
    df.at[idx, "tp"] = num(tp)

    ex = ccxt.bingx({"enableRateLimit": True})
    try:
        price = num(ex.fetch_ticker(df.at[idx, "symbol"])["last"])
    except Exception:
        df.to_csv(TRADES_FILE, index=False)
        return {"status": "saved", "note": "price fetch failed"}

    entry = num(df.at[idx, "entry_price"])
    qty = num(df.at[idx, "qty"])
    unreal = num((price - entry) * qty)

    df.at[idx, "current_price"] = price
    df.at[idx, "unrealized_pnl"] = unreal

    sl_val = num(sl)
    tp_val = num(tp)

    if tp_val > 0 and price >= tp_val:
        df.at[idx, "exit_price"] = price
        df.at[idx, "pnl"] = unreal
        df.at[idx, "status"] = "closed"
    elif sl_val > 0 and price <= sl_val:
        df.at[idx, "exit_price"] = price
        df.at[idx, "pnl"] = unreal
        df.at[idx, "status"] = "closed"

    df.to_csv(TRADES_FILE, index=False)
    update_stats()

    return {
        "trade_id": trade_id,
        "price": price,
        "sl": sl_val,
        "tp": tp_val,
        "status": df.at[idx, "status"],
    }


# ------------------------
# PAPER SELL (PARTIAL CLOSE)
# ------------------------
@app.post("/paper-sell")
def paper_sell(
    trade_id: str = Query(...),
    sell_pct: float = Query(100.0),
):
    df = ensure_trades_df()

    row = df[(df["id"] == trade_id) & (df["status"] == "open")]
    if row.empty:
        return {"error": "Trade not found or already closed"}

    idx = row.index[0]
    r = df.loc[idx]

    ex = ccxt.bingx({"enableRateLimit": True})
    try:
        price = num(ex.fetch_ticker(r["symbol"])["last"])
    except Exception:
        return {"error": "Price fetch failed"}

    entry_price = num(r["entry_price"])
    qty = num(r["qty"])

    # ---------- PARTIAL CLOSE CALC ----------
    raw_close_qty = qty * (sell_pct / 100.0)
    close_qty = num(raw_close_qty)

    # ✅ if quantity becomes too small, force full close
    if close_qty <= 0 or close_qty >= qty or qty - close_qty < qty * MIN_CLOSE_QTY_PCT:
        pnl = safe((price - entry_price) * qty)

        df.at[idx, "exit_price"] = price
        df.at[idx, "pnl"] = pnl
        df.at[idx, "status"] = "closed"

        df.to_csv(TRADES_FILE, index=False)
        update_stats()

        return {
            "status": "closed",
            "closed_qty": qty,
            "remaining_qty": 0,
            "exit_price": price,
            "pnl": pnl,
        }

    # ---------- PARTIAL CLOSE ----------
    remain_qty = safe(qty - close_qty)
    pnl = safe((price - entry_price) * close_qty)

    # update remaining open position
    df.at[idx, "qty"] = remain_qty
    df.at[idx, "used_usd"] = safe(entry_price * remain_qty)

    # create closed trade record
    closed = r.copy()
    closed["id"] = str(uuid.uuid4())
    closed["qty"] = close_qty
    closed["used_usd"] = safe(entry_price * close_qty)
    closed["exit_price"] = price
    closed["pnl"] = pnl
    closed["status"] = "closed"

    df = pd.concat([df, closed.to_frame().T], ignore_index=True)

    df.to_csv(TRADES_FILE, index=False)
    update_stats()

    return {
        "status": "partial",
        "closed_qty": close_qty,
        "remaining_qty": remain_qty,
        "exit_price": price,
        "pnl": pnl,
    }


# ------------------------
# AUTO STRATEGY
# ------------------------
def fetch_ohlcv(symbol, tf="1m", limit=200):
    ex = ccxt.bingx({"enableRateLimit": True})
    data = ex.fetch_ohlcv(symbol, tf, limit=limit)
    df = pd.DataFrame(
        data, columns=["ts", "open", "high", "low", "close", "volume"]
    )
    return df


def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()


def rsi(series, n=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(alpha=1 / n, adjust=False).mean()
    ma_down = down.ewm(alpha=1 / n, adjust=False).mean()
    rs = ma_up / (ma_down + 1e-9)
    return 100 - (100 / (1 + rs))


def strategy_step():
    if not AUTO_STRATEGY_ENABLED or not AUTO_TRADING_ENABLED:
        return

    for symbol in STRATEGY_SYMBOLS:

        # load OHLCV
        try:
            df = fetch_ohlcv(symbol, STRATEGY_TIMEFRAME, limit=200)
        except:
            continue
        
        if df.empty:
            continue

        # indicators
        df["ema_fast"] = ema(df["close"], EMA_FAST)
        df["ema_slow"] = ema(df["close"], EMA_SLOW)
        df["rsi_val"] = rsi(df["close"], RSI_PERIOD)
        last = df.iloc[-1]

        ema_fast = last["ema_fast"]
        ema_slow = last["ema_slow"]
        rsi_val = last["rsi_val"]

        if math.isnan(ema_fast) or math.isnan(ema_slow) or math.isnan(rsi_val):
            continue

        # check open position for this symbol
        book = ensure_trades_df()
        open_pos = book[(book["symbol"] == symbol) & (book["status"] == "open")]
        has_position = not open_pos.empty

        # signals
        long_signal = (ema_fast > ema_slow) and (40 < rsi_val < 70)
        exit_signal = (ema_fast < ema_slow) or (rsi_val > 70)

        # BUY
        if not has_position and long_signal:
            print(f"📈 AUTO BUY {symbol} | RSI: {rsi_val}")
            paper_buy(symbol=symbol, size_pct=STRATEGY_SIZE_PCT, sl_pct=0.6, tp_pct=1.2)
            continue

        # SELL
        if has_position and exit_signal:
            trade_id = open_pos.iloc[0]["id"]
            print(f"📉 AUTO SELL {symbol} | RSI: {rsi_val}")
            paper_sell(trade_id=trade_id, sell_pct=100)
            continue


# ------------------------
# BACKGROUND LOOPS
# ------------------------
async def watcher_loop():
    while True:
        try:
            refresh_prices()
        except Exception as e:
            print("Watcher error:", e)
        await asyncio.sleep(WATCHER_INTERVAL)


async def strategy_loop():
    while True:
        try:
            strategy_step()
        except Exception as e:
            print("Strategy error:", e)
        await asyncio.sleep(STRATEGY_INTERVAL)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(watcher_loop())
    asyncio.create_task(strategy_loop())


