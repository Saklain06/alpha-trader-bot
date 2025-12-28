# ==============================
# main.py — SOLID DATABASE VERSION
# ==============================

from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import ccxt.async_support as ccxt
import uuid
import math
import asyncio
from datetime import datetime, timezone, date
import logging
from typing import Optional
import pandas as pd
import numpy as np

# [NEW] Import Database
from database import db

# ------------------------
# LOGGING
# ------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TradingBot")

# ------------------------
# EXCHANGE (ASYNC)
# ------------------------
ex_live = ccxt.bingx({
    "apiKey": os.getenv("BINGX_API_KEY"),
    "secret": os.getenv("BINGX_SECRET_KEY"),
    "enableRateLimit": True,
    "options": {
        "defaultType": "spot"
    }
})

# ------------------------
# LIVE / PAPER MODE
# ------------------------
TRADE_MODE = os.environ.get("TRADE_MODE", "paper")
logger.info(f"TRADE_MODE: {TRADE_MODE}")

# ------------------------
# CONFIG
# ------------------------
STRATEGY_BOLLINGER_REVERSION = "bollinger_reversion"
STRATEGY_NAME = STRATEGY_BOLLINGER_REVERSION # Switched from Momentum
AUTO_TRADING_ENABLED = True
BASE_BALANCE = 200.0

MAX_SYMBOL_EXPOSURE_USD = float(os.environ.get("MAX_SYMBOL_EXPOSURE_USD", "120.0"))
MAX_HOLD_SECONDS = 12 * 3600
MAX_FLAT_PNL_PCT = 0.5
WATCHER_INTERVAL = 5
STRATEGY_INTERVAL = 60 # Check every minute
MIN_CLOSE_QTY_PCT = 0.15
COMMISSION_PCT = float(os.environ.get("COMMISSION_PCT", "0.001"))
DEFAULT_SLIPPAGE_PCT = float(os.environ.get("DEFAULT_SLIPPAGE_PCT", "0.001"))
MAX_DAILY_LOSS_USD = float(os.environ.get("MAX_DAILY_LOSS_USD", "500.0"))
MAX_ORDER_USD = float(os.environ.get("MAX_ORDER_USD", "120.0"))
MAX_POSITION_COUNT = int(os.environ.get("MAX_POSITION_COUNT", "20"))
MAX_TRADES_PER_DAY = int(os.environ.get("MAX_TRADES_PER_DAY", "200"))
PER_SYMBOL_COOLDOWN_SEC = int(os.environ.get("PER_SYMBOL_COOLDOWN_SEC", "300"))
near_hits = [] # [NEW] Global storage for interesting setups

# ------------------------
# FASTAPI APP
# ------------------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------
# INIT DB
# ------------------------
@app.on_event("startup")
async def startup():
    await db.init_db()
    
    # Init default state
    state = await db.get_state()
    if "auto_trading" not in state:
        await db.set_state_key("auto_trading", AUTO_TRADING_ENABLED)
    if "daily_realized_pnl" not in state:
         await db.set_state_key("daily_realized_pnl", 0.0)
    if "trades_today" not in state:
         await db.set_state_key("trades_today", 0)
    if "last_reset_date" not in state:
        await db.set_state_key("last_reset_date", str(date.today()))
    if "kill_switch" not in state:
        await db.set_state_key("kill_switch", False)
    if "trade_usd" not in state:
        await db.set_state_key("trade_usd", 20.0)

    asyncio.create_task(watcher_loop())
    asyncio.create_task(strategy_loop())

# ------------------------
# UTILS
# ------------------------
def safe(v):
    try:
        v = float(v)
        if math.isnan(v) or math.isinf(v): return 0.0
        return round(v, 6)
    except: return 0.0

def num(v):
    return safe(v)

async def safe_fetch_ticker(symbol):
    try:
        return await ex_live.fetch_ticker(symbol)
    except Exception as e:
        logger.warning(f"[TICKER ERROR] {symbol}: {e}")
        return None

def bollinger_entry_ok(symbol, candles):
    try:
        if not candles or len(candles) < 20: return False
        
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        curr = df.iloc[-1]
        
        # Calc BB (20, 2)
        sma = df['close'].rolling(20).mean()
        std = df['close'].rolling(20).std()
        lower = sma - (std * 2)
        
        # Calc RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        curr_rsi = rsi.iloc[-1]
        curr_lower = lower.iloc[-1]
        
        # LOGIC: Price < Lower Band AND RSI < 30 (Oversold Dip)
        is_dip = curr['close'] < curr_lower
        is_oversold = curr_rsi < 30
        
        return is_dip and is_oversold
    except Exception as e:
        logger.error(f"[STRATEGY ERROR] {e}")
        return False


# ------------------------
# DAILY RESET
# ------------------------
async def daily_reset_if_needed():
    state = await db.get_state()
    today = str(date.today())
    if state.get("last_reset_date") != today:
        await db.set_state_key("last_reset_date", today)
        await db.set_state_key("daily_realized_pnl", 0.0)
        await db.set_state_key("trades_today", 0)
        await db.set_state_key("last_trade_ts_map", {})

# ------------------------
# STATE HELPERS
# ------------------------
async def get_app_state():
    return await db.get_state()

# ------------------------
# ACCOUNTING
# ------------------------
async def get_equity_locked_free():
    if TRADE_MODE == "live":
        try:
            # Get all balances
            balance = await ex_live.fetch_balance()
            free_usdt = safe(balance.get("USDT", {}).get("free", 0))
            
            # Fetch tickers to value other coins
            tickers = await ex_live.fetch_tickers()
            
            total_holdings_usd = 0.0
            for coin, data in balance['total'].items():
                if coin == 'USDT': continue
                qty = num(data)
                if qty <= 0: continue
                
                symbol = f"{coin}/USDT"
                if symbol in tickers:
                    price = num(tickers[symbol]['last'])
                    total_holdings_usd += (qty * price)
            
            total_equity = safe(free_usdt + total_holdings_usd)
            # "Locked" in the bot's context is the value of coins the bot is MANAGING
            open_trades = await db.get_open_trades()
            invested_by_bot = sum(t['used_usd'] for t in open_trades)
            
            return total_equity, safe(invested_by_bot), free_usdt
        except Exception as e:
            logger.warning(f"[BALANCE ERROR] {e}")
            return 0.0, 0.0, 0.0

    # Paper mode calculation
    open_trades = await db.get_open_trades()
    state = await db.get_state()
    total_realized = state.get("total_realized_pnl", 0.0)
    locked = sum(t['used_usd'] for t in open_trades)
    unreal = sum(t['unrealized_pnl'] for t in open_trades)
    
    equity = BASE_BALANCE + total_realized + unreal
    free = max(0.0, BASE_BALANCE + total_realized - locked)
    return safe(equity), safe(locked), safe(free)

# ------------------------
# SAFETY CHECKS
# ------------------------
async def can_place_trade(symbol, usd, strategy):
    state = await get_app_state()
    
    if state.get("kill_switch"): return False, "kill_switch"
    if state.get("daily_realized_pnl", 0) <= -abs(MAX_DAILY_LOSS_USD): return False, "daily_loss_limit"
    if usd > MAX_ORDER_USD: return False, "order_too_large"
    if state.get("trades_today", 0) >= MAX_TRADES_PER_DAY: return False, "trade_limit"

    open_trades = await db.get_open_trades()
    if len(open_trades) >= MAX_POSITION_COUNT: return False, "max_positions"
    
    # Cooldown
    ts_map = state.get("last_trade_ts_map", {})
    key = f"{strategy}:{symbol}"
    last_ts = ts_map.get(key, 0)
    if (datetime.now().timestamp() - last_ts) < PER_SYMBOL_COOLDOWN_SEC:
        return False, "cooldown"

    return True, "ok"

async def register_trade_open(symbol, strategy):
    state = await get_app_state()
    
    # Update trades today
    current_today = state.get("trades_today", 0) + 1
    await db.set_state_key("trades_today", current_today)
    
    # Update Timestamp map
    ts_map = state.get("last_trade_ts_map", {})
    ts_map[f"{strategy}:{symbol}"] = datetime.now().timestamp()
    await db.set_state_key("last_trade_ts_map", ts_map)

async def register_trade_close(pnl):
    state = await get_app_state()
    
    # Daily PnL
    daily = state.get("daily_realized_pnl", 0.0) + pnl
    await db.set_state_key("daily_realized_pnl", daily)
    
    # Total PnL
    total = state.get("total_realized_pnl", 0.0) + pnl
    await db.set_state_key("total_realized_pnl", total)

async def symbol_exposure_ok(symbol, additional_usd):
    trades = await db.get_open_trades()
    exposure = sum(t['used_usd'] for t in trades if t['symbol'] == symbol)
    return (exposure + additional_usd) <= MAX_SYMBOL_EXPOSURE_USD

# ------------------------
# BUY LOGIC
# ------------------------
async def execute_buy(symbol, sl_pct, tp_pct, strategy):
    await daily_reset_if_needed()
    
    # Check Funds
    _, _, free = await get_equity_locked_free()
    state = await get_app_state()
    trade_usd = float(state.get("trade_usd", 10.0))
    # Cap trade size at free balance
    # [SAFETY] Add 2% buffer for exchange market-order-requirements/fees
    usd = min(trade_usd, free) * 0.98
    
    if usd < 5: return # Too small
    
    if not await symbol_exposure_ok(symbol, usd): return
    ok, reason = await can_place_trade(symbol, usd, strategy)
    if not ok: return

    ticker = await safe_fetch_ticker(symbol)
    if not ticker: return
    
    price = num(ticker["last"])
    
    # Execution
    if TRADE_MODE == "live":
        try:
            amount = usd / price
            # BingX Precision
            await ex_live.load_markets() # Ensure markets are loaded
            amount = num(ex_live.amount_to_precision(symbol, amount))
            
            order = await ex_live.create_market_buy_order(symbol, amount)
            # Robust price fetching
            exec_price = num(order.get("average") or order.get("price") or price)
            qty = num(order.get("filled") or 0)
            
            if qty <= 0:
                # If order filled field is missing, check fetch_order
                try:
                    order = await ex_live.fetch_order(order['id'], symbol)
                    qty = num(order.get("filled") or 0)
                    exec_price = num(order.get("average") or order.get("price") or price)
                except: pass
            
            used = safe(exec_price * qty)
            
            # [SYNC] Fetch real fees from BingX
            fee_obj = order.get('fee')
            if fee_obj and fee_obj.get('cost') is not None:
                fee_cost = num(fee_obj['cost'])
                fee_currency = fee_obj.get('currency')
                # If fee paid in Base (e.g. BTC), convert to USDT
                if fee_currency and fee_currency == symbol.split('/')[0]:
                    fees = safe(fee_cost * exec_price)
                else:
                    fees = safe(fee_cost) # Assumes USDT
            else:
                fees = safe(used * COMMISSION_PCT)
        except Exception as e:
            logger.error(f"[BUY FAIL] {symbol}: {e}")
            return
    else:
        # Paper
        exec_price = price
        qty = safe(usd / price)
        used = safe(qty * exec_price)
        fees = safe(used * COMMISSION_PCT)

    if qty <= 0: return

    sl = safe(exec_price * (1 - sl_pct / 100)) if sl_pct else 0.0
    tp = safe(exec_price * (1 + tp_pct / 100)) if tp_pct else 0.0

    # Merge or New
    existing = await db.get_trades_by_status_symbol_strategy("open", symbol, strategy)
    
    if existing:
        pos = existing[0]
        old_qty, old_entry = pos['qty'], pos['entry_price']
        total_qty = safe(old_qty + qty)
        avg_entry = safe(((old_qty * old_entry) + (qty * exec_price)) / total_qty)
        
        await db.update_trade(pos['id'], {
            "qty": total_qty,
            "entry_price": avg_entry,
            "used_usd": safe(pos['used_usd'] + used),
            "fees_usd": safe(pos['fees_usd'] + fees),
            "sl": min(pos['sl'], sl) if sl and pos['sl'] else (pos['sl'] or sl),
            "tp": max(pos['tp'], tp) if tp and pos['tp'] else (pos['tp'] or tp)
        })
    else:
        trade = {
            "id": str(uuid.uuid4()),
            "time": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "side": "buy",
            "strategy": strategy,
            "entry_price": exec_price,
            "qty": qty,
            "used_usd": used,
            "status": "open",
            "pnl": 0.0,
            "sl": sl,
            "tp": tp,
            "exit_price": 0.0,
            "current_price": price,
            "unrealized_pnl": 0.0,
            "fees_usd": fees,
            "highest_price": price,
            "trail_active": False,
            "trail_sl": 0.0
        }
        await db.add_trade(trade)
    
    await register_trade_open(symbol, strategy)
    logger.info(f"[BUY] {symbol} @ {exec_price}")

# ------------------------
# SELL LOGIC
# ------------------------
async def execute_sell(trade_id, pct=100.0, reason="manual"):
    try:
        trade = await db.get_trade(trade_id)
        if not trade or trade['status'] != 'open': return

        ticker = await safe_fetch_ticker(trade['symbol'])
        if not ticker: return
            
        price = num(ticker["last"])
        
        sell_qty = safe(trade['qty'] * pct / 100)
        if sell_qty <= 0: return

        # Execution
        if TRADE_MODE == "live":
            try:
                bal = await ex_live.fetch_balance()
                base = trade['symbol'].split('/')[0]
                available = bal.get(base, {}).get('free', 0)
                
                # Dust Safety
                if available < sell_qty:
                    sell_qty = available
                
                # Min Notion Safety
                if (sell_qty * price) < 5.0 and pct < 99:
                     return

                # Precision
                sell_qty_prec = num(ex_live.amount_to_precision(trade['symbol'], sell_qty))
                
                order = await ex_live.create_market_sell_order(trade['symbol'], sell_qty_prec)
                # Robust price fetching
                exec_price = num(order.get("average") or order.get("price") or price)
                qty_sold = num(order.get("filled") or sell_qty_prec)
                
                if num(order.get("filled", 0)) <= 0:
                     try:
                        order = await ex_live.fetch_order(order['id'], trade['symbol'])
                        exec_price = num(order.get("average") or order.get("price") or price)
                        qty_sold = num(order.get("filled") or sell_qty_prec)
                     except: pass
                
                sell_qty = qty_sold # Use actual filled qty if possible
                
                # [SYNC] Fetch real fees from BingX
                fee_obj = order.get('fee')
                if fee_obj and fee_obj.get('cost') is not None:
                    fees = num(fee_obj['cost'])
                    # Fee on sell is usually USDT
                else:
                    fees = safe(exec_price * sell_qty * COMMISSION_PCT)
            except Exception as e:
                logger.error(f"[SELL FAIL] {trade['symbol']}: {e}")
                return
        else:
            exec_price = price
            fees = safe(exec_price * sell_qty * COMMISSION_PCT)

        pnl = safe((exec_price - trade['entry_price']) * sell_qty - fees)
        
        remaining = safe(trade['qty'] - sell_qty)
        
        # Clean Dust
        if remaining * price < 2.0 or pct >= 99.0:
            await db.update_trade(trade_id, {
                "status": "closed",
                "qty": 0,
                "used_usd": 0,
                "exit_price": exec_price,
                "pnl": safe(trade['pnl'] + pnl),
                "fees_usd": safe(trade['fees_usd'] + fees),
                "exit_time": datetime.utcnow().isoformat()
            })
            await register_trade_close(pnl)
            logger.info(f"[SELL FULL] {trade['symbol']} PnL: {pnl} ({reason})")
        else:
            await db.update_trade(trade_id, {
                "qty": remaining,
                "used_usd": safe(trade['used_usd'] * (remaining / trade['qty'])),
                "pnl": safe(trade['pnl'] + pnl),
                "fees_usd": safe(trade['fees_usd'] + fees)
            })
            logger.info(f"[SELL PARTIAL] {trade['symbol']} PnL: {pnl}")
            
    except Exception as e:
        logger.exception(f"[EXECUTE SELL ERROR] {trade_id}")

# ------------------------
# LOOPS
# ------------------------
async def watcher_loop():
    logger.info("Watcher started")
    while True:
        try:
            trades = await db.get_open_trades()
            if not trades:
                await asyncio.sleep(WATCHER_INTERVAL)
                continue

            for t in trades:
                ticker = await safe_fetch_ticker(t['symbol'])
                if not ticker: continue
                price = num(ticker['last'])
                
                unreal = (price - t['entry_price']) * t['qty']
                highest = max(t['highest_price'], price)
                
                updates = {
                    "current_price": price,
                    "unrealized_pnl": safe(unreal),
                    "highest_price": highest
                }

                # Dynamic Trailing
                # Activate at 1.5%, Trail 2%
                gain_pct = ((price - t['entry_price']) / t['entry_price']) * 100
                
                if not t['trail_active']:
                    if gain_pct >= 1.5: 
                        updates['trail_active'] = 1
                        updates['trail_sl'] = safe(highest * 0.98)
                        logger.info(f"[TRAIL ON] {t['symbol']}")
                elif t['trail_active']:
                    new_trail = safe(highest * 0.98)
                    if new_trail > t['trail_sl']:
                        updates['trail_sl'] = new_trail

                should_close = False
                reason = ""
                
                if t['sl'] > 0 and price <= t['sl']:
                    should_close = True; reason = "sl"
                elif t['tp'] > 0 and price >= t['tp']:
                    should_close = True; reason = "tp"
                elif t.get('trail_active') and price <= updates.get('trail_sl', 0):
                    should_close = True; reason = "trail"
                
                await db.update_trade(t['id'], updates)
                
                if should_close:
                    await execute_sell(t['id'], 100, reason)

        except Exception as e:
            logger.exception("Watcher error")
        
        await asyncio.sleep(WATCHER_INTERVAL)

# [NEW] Import Logic
from logic.alpha_hunter import AlphaHunter

async def strategy_loop():
    logger.info("Alpha Hunter Strategy Started...")
    ignored = ["USDC", "USDP", "FDUSD", "TUSD", "EUR", "GBP", "DAI"]
    
    while True:
        try:
            state = await get_app_state()
            if not state.get("auto_trading"):
                await asyncio.sleep(5)
                continue
            
            # 1. Fetch all tickers to filter candidates
            try:
                tickers = await ex_live.fetch_tickers()
            except Exception as e:
                logger.error(f"[SCAN ERROR] Fetch tickers failed: {e}")
                await asyncio.sleep(10)
                continue

            # 2. Filter for USDT pairs with Volume > $100k
            candidates = []
            for s, t in tickers.items():
                if "/USDT" in s and t['quoteVolume'] > 100_000:
                    base = s.split('/')[0]
                    if base not in ignored:
                        candidates.append(s)
            
            logger.info(f"[SCANNER] Scanning {len(candidates)} pairs for Alpha setups...")
            
            # 3. Batch Scan (Chunks of 5 to respect rate limits)
            chunk_size = 5
            for i in range(0, len(candidates), chunk_size):
                if not state.get("auto_trading"): break # Stop if disabled
                
                batch = candidates[i:i+chunk_size]
                
                for symbol in batch:
                    try:
                        # Fetch last 24h (24 candles of 1h)
                        ohlcv = await ex_live.fetch_ohlcv(symbol, '1h', limit=25)
                        
                        # Use Modular Logic
                        signal, diagnostic = AlphaHunter.check_signal(symbol, ohlcv)
                        
                        if diagnostic:
                            # Update near_hits
                            diagnostic['time'] = datetime.now(timezone.utc).isoformat()
                            near_hits.insert(0, diagnostic)
                            while len(near_hits) > 20: near_hits.pop()

                        if signal:
                            await execute_buy(symbol, 4.0, 0.0, "alpha_hunter")
                            
                    except Exception as e:
                        logger.error(f"[SCANNER ERROR] {symbol}: {e}")
                
                # Rate Limit Sleep between chunks  
                await asyncio.sleep(1.0) 
            
            logger.info("[SCANNER] Cycle complete. Sleeping...")
            
        except Exception as e:
            logger.exception("Strategy loop crashed")
        
        # Scan every 5 minutes during tuning
        await asyncio.sleep(60 * 5)

# ------------------------
# ENDPOINTS
# ------------------------
@app.get("/stats")
async def stats():
    equity, locked, free = await get_equity_locked_free()
    state = await get_app_state()
    
    all_trades = await db.get_all_trades_desc(limit=500)
    closed = [t for t in all_trades if t['status'] == 'closed']
    wins = [t for t in closed if t['pnl'] > 0]
    total_realized_pnl = sum(t['pnl'] for t in closed)
    
    # [NEW] Unrealized PnL from open trades
    open_trades = await db.get_open_trades()
    total_unrealized_pnl = sum(t.get('unrealized_pnl', 0.0) for t in open_trades)
    
    return {
        "balance": equity,
        "locked": locked,
        "free": free,
        "mode": "auto" if state.get("auto_trading") else "manual",
        "total_pnl": safe(total_realized_pnl + total_unrealized_pnl),
        "realized_pnl": safe(total_realized_pnl),
        "unrealized_pnl": safe(total_unrealized_pnl),
        "win_rate": safe((len(wins)/len(closed)*100) if closed else 0),
        "total_trades": len(closed)
    }

@app.get("/trades")
async def get_trades():
    return await db.get_all_trades_desc()

@app.get("/positions")
async def get_positions():
    return await db.get_open_trades()

@app.get("/signals")
async def get_signals():
    return near_hits

@app.post("/paper-sell")
async def paper_sell(trade_id: str = Query(...), sell_pct: float = Query(100.0)):
    await execute_sell(trade_id, sell_pct, reason="manual_web")
    return {"status": "ok"}

@app.post("/update-sl-tp")
async def update_sl_tp(trade_id: str = Query(...), sl: float = Query(...), tp: float = Query(...)):
    await db.update_trade(trade_id, {"sl": sl, "tp": tp})
    return {"status": "ok"}

@app.post("/admin/kill")
async def kill():
    await db.set_state_key("kill_switch", True)
    await db.set_state_key("auto_trading", False)
    return {"status": "killed"}

@app.post("/admin/resume")
async def resume():
    await db.set_state_key("kill_switch", False)
    await db.set_state_key("auto_trading", True)
    return {"status": "resumed"}

@app.get("/admin/trade-usd")
async def get_trade_usd():
    state = await get_app_state()
    return {"trade_usd": state.get("trade_usd", 10.0)}

@app.post("/admin/set-trade-usd")
async def set_trade_usd(amount: float = Query(..., gt=0)):
    await db.set_state_key("trade_usd", float(amount))
    return {"status": "ok"}
