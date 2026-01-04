# ==============================================================================
# BINANCE MULTI-STRATEGY TRADING BOT (PRODUCTION V2)
# ==============================================================================
# Standard Imports
import os
import math
import uuid
import asyncio
import logging
from datetime import datetime, timezone, date
from typing import Optional

# Third-Party Imports
import pandas as pd
# import numpy as np # Unused
from dotenv import load_dotenv
import ccxt.async_support as ccxt
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

# Local Imports
from database import db
from logic.alpha_hunter import AlphaHunter
from logic.smc_utils import SMCManager
from logic.indicators import check_volatility_ok

load_dotenv()

# ------------------------
# LOGGING
# ------------------------
# ------------------------
# LOGGING (ROTATING)
# ------------------------
from logging.handlers import RotatingFileHandler
logger = logging.getLogger("TradingBot")
logger.setLevel(logging.INFO)

# File Handler with Rotation (10MB, keep 5)
file_handler = RotatingFileHandler("server.log", maxBytes=10*1024*1024, backupCount=5)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# Stream Handler (Stdout)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# ------------------------
# EXCHANGE (ASYNC)
# ------------------------
ex_live = ccxt.binance({
    "apiKey": os.getenv("BINANCE_API_KEY"),
    "secret": os.getenv("BINANCE_SECRET_KEY"),
    "enableRateLimit": True,
    "options": {
        "defaultType": "spot",
        "adjustForTimeDifference": True
    }
})

# ------------------------
# LIVE / PAPER MODE
# ------------------------
TRADE_MODE = os.environ.get("TRADE_MODE", "paper")
logger.info(f"TRADE_MODE: {TRADE_MODE}")

# ------------------------------------------------------------------------------
# CONFIG & CONSTANTS
# ------------------------------------------------------------------------------
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
MAX_DAILY_LOSS_USD = float(os.environ.get("MAX_DAILY_LOSS_USD", "100.0"))
MAX_ORDER_USD = float(os.environ.get("MAX_ORDER_USD", "120.0"))

# [QUANT UPDATES] Low frequency, High quality
MAX_POSITION_COUNT = int(os.environ.get("MAX_POSITION_COUNT", "12"))
MAX_TRADES_PER_DAY = 30
PER_SYMBOL_COOLDOWN_SEC = 6 * 3600 # 6 Hours
MAX_BOLLINGER_POSITIONS = 1
near_hits = [] # Global storage for interesting setups

# [HARDENING] Global Safety State
cached_regime = {"value": "bearish", "ts": 0}
consecutive_api_errors = 0
pause_until_ts = 0
err_lock = asyncio.Lock()

def min_notional_ok(symbol, usd):
    market = ex_live.markets.get(symbol)
    if not market:
        return False

    limits = market.get("limits", {})
    cost_min = limits.get("cost", {}).get("min", 0)

    return usd >= cost_min


def log_regime_change(old, new):
    if old != new:
        logger.info(f"🟢 [REGIME CHANGE] {old} → {new}")

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
    
    # [SAFETY] Sync DB with Exchange on Boot
    asyncio.create_task(sync_portfolio_with_exchange())
    
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

    # [HARDENING] Move load_markets to startup
    try:
        await ex_live.load_markets()
        logger.info("📡 [EXCHANGE] Markets loaded successfully.")
    except Exception as e:
        logger.error(f"❌ [EXCHANGE INIT ERROR] {e}")

    asyncio.create_task(watcher_loop())
    asyncio.create_task(strategy_loop())

# ------------------------
# UTILS
# ------------------------
def safe(v, dec=10):
    try:
        v = float(v)
        if math.isnan(v) or math.isinf(v): return 0.0
        return round(v, dec)
    except: return 0.0

def num(v):
    return safe(v)

async def safe_fetch_ticker(symbol):
    global consecutive_api_errors, pause_until_ts
    try:
        ticker = await ex_live.fetch_ticker(symbol)
        async with err_lock:
            consecutive_api_errors = 0 
        return ticker
    except Exception as e:
        async with err_lock:
            consecutive_api_errors += 1
            logger.warning(f"⚠️ [API ERROR] {symbol}: {e} (Consecutive: {consecutive_api_errors})")
            if consecutive_api_errors >= 5:
                pause_until_ts = datetime.now().timestamp() + (15 * 60)
                logger.critical("🚨 [CRITICAL] 5+ Consecutive API Errors. Pausing for 15 mins.")
        return None

def bollinger_entry_ok(symbol, candles):
    try:
        if not candles or len(candles) < 21: return False
        
        df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Calc BB (20, 2)
        sma = df['close'].rolling(20).mean()
        std = df['close'].rolling(20).std()
        lower = sma - (std * 2)
        
        # [QUANT] Volatility Check (Applied to all)
        vol_ok, _ = check_volatility_ok(df, '15m')
        if not vol_ok: return False

        # Calc RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss.replace(0, 0.0001))
        rsi = 100 - (100 / (1 + rs))
        
        curr_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-2]
        curr_lower = lower.iloc[-1]
        
        # [QUANT] Confirmation:
        # 1. Price CLOSES back ABOVE lower band
        # 2. RSI is rising (current > previous)
        is_closing_above = curr['close'] > curr_lower and prev['close'] <= lower.iloc[-2]
        is_rsi_rising = curr_rsi > prev_rsi
        is_oversold = curr_rsi < 35 # Slightly relaxed threshold for confirmation entries
        
        return is_closing_above and is_rsi_rising and is_oversold
    except Exception as e:
        logger.error(f"[BOL ERROR] {e}")
        return False

# [HARDENING] Market Regime Detection (3-State + 5m Cache)
async def get_btc_regime():
    global cached_regime
    now = datetime.now().timestamp()
    
    # Return cached value if within 5 minutes
    if (now - cached_regime["ts"]) < 300:
        return cached_regime["value"]

    try:
        ohlcv = await ex_live.fetch_ohlcv("BTC/USDT", "1h", limit=210)
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        ema50 = df['close'].ewm(span=50, adjust=False).mean()
        ema200 = df['close'].ewm(span=200, adjust=False).mean()
        
        last_ema50 = ema50.iloc[-1]
        last_ema200 = ema200.iloc[-1]
        
        new_regime = "bearish"
        if last_ema50 > last_ema200:
            diff_pct = abs(last_ema50 - last_ema200) / last_ema200 * 100
            if diff_pct < 0.5:
                new_regime = "flat"
            else:
                new_regime = "bullish"
        
        log_regime_change(cached_regime["value"], new_regime)
        cached_regime = {"value": new_regime, "ts": now}
        return new_regime
    except Exception as e:
        logger.error(f"❌ [REGIME ERROR] {e}")
        return "bearish"


# ------------------------
# DAILY RESET
# ------------------------
async def daily_reset_if_needed():
    state = await db.get_state()
    today = str(date.today())
    # If it's a new day, clear all daily trackers
    if state.get("last_reset_date") != today:
        logger.info(f"[RESET] New day detected ({today}). Clearing daily stats.")
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
            
            return total_equity, safe(invested_by_bot), free_usdt, "ok", None
        except Exception as e:
            logger.warning(f"[BALANCE ERROR] {e}")
            return 0.0, 0.0, 0.0, "error", str(e)

    # Paper mode calculation
    open_trades = await db.get_open_trades()
    state = await db.get_state()
    total_realized = state.get("total_realized_pnl", 0.0)
    locked = sum(t['used_usd'] for t in open_trades)
    unreal = sum(t['unrealized_pnl'] for t in open_trades)
    
    equity = BASE_BALANCE + total_realized + unreal
    free = max(0.0, BASE_BALANCE + total_realized - locked)
    return safe(equity), safe(locked), safe(free), "ok", None

# ------------------------------------------------------------------------------
# RISK & UTILITIES
# ------------------------------------------------------------------------------
def calculate_position_limits(equity: float, locked: float, free: float, 
                               open_position_count: int) -> tuple:
    """
    Dynamic capital allocation with safety buffers.
    
    Returns: (max_positions, trade_usd)
    
    Strategy:
    - Target 95% equity deployment (5% buffer)
    - 1 position per $30 equity (conservative scaling)
    - Min 3 positions, Max 12 positions
    - Distribute remaining capital across remaining slots
    """
    # Dynamic max positions: 1 position per $30 of equity
    # Min 3 (allow small accounts to trade), Max 12 (prevent over-diversification)
    calculated_max_pos = max(3, min(12, int(equity / 30)))
    
    # Respect hard cap from config (backward compatibility)
    max_positions = min(calculated_max_pos, MAX_POSITION_COUNT)
    
    # [SAFETY] Defensive guard: prevent edge-case over-allocation
    if open_position_count >= max_positions:
        return max_positions, 0.0
    
    # Calculate per-trade allocation
    remaining_slots = max(1, max_positions - open_position_count)
    
    # Use 95% of free capital, distributed across remaining slots
    trade_usd = (free * 0.95) / remaining_slots
    
    # Enforce minimum viable trade size ($10)
    trade_usd = max(10.0, trade_usd)
    
    # Respect MAX_ORDER_USD hard cap (from env)
    trade_usd = min(trade_usd, MAX_ORDER_USD)
    
    return max_positions, trade_usd

async def can_place_trade(symbol, usd, strategy, equity, locked, free):
    """
    Check if a trade can be placed based on all safety constraints.
    
    Args:
        equity, locked, free: Pre-calculated capital values to avoid duplicate calls
    """
    global pause_until_ts
    state = await get_app_state()
    
    # [HARDENING] API Stability Check
    if datetime.now().timestamp() < pause_until_ts:
        return False, "api_stability_pause"

    if state.get("kill_switch"): return False, "kill_switch"
    if state.get("daily_realized_pnl", 0) <= -abs(MAX_DAILY_LOSS_USD): return False, "daily_loss_limit"
    if usd > MAX_ORDER_USD: return False, "order_too_large"
    if state.get("trades_today", 0) >= MAX_TRADES_PER_DAY: return False, "trade_limit"

    open_trades = await db.get_open_trades()
    
    # [DYNAMIC] Calculate position limits based on current capital (passed in)
    max_positions, _ = calculate_position_limits(equity, locked, free, len(open_trades))
    
    if len(open_trades) >= max_positions: 
        return False, f"max_positions ({len(open_trades)}/{max_positions})"
    
    # [QUANT] Prevent strategy stacking on same symbol
    existing_symbol_trades = [t for t in open_trades if t['symbol'] == symbol]
    if existing_symbol_trades:
        return False, "symbol_already_held"

    # [QUANT] 3-State Regime Filter
    regime = await get_btc_regime()
    if regime == "bearish":
        return False, "regime_bearish"
    
    if strategy == "alpha_hunter" and regime != "bullish":
        return False, f"alpha_not_allowed_in_{regime}"
        
    if strategy == "bollinger_reversion":
        if regime != "flat":
            return False, f"bb_not_allowed_in_{regime}"
        # Limit Bollinger to 1 at a time
        bb_trades = [t for t in open_trades if t['strategy'] == "bollinger_reversion"]
        if len(bb_trades) >= MAX_BOLLINGER_POSITIONS:
            return False, "max_bb_positions"

    # [QUANT] 3-Hour Post-Exit Cooldown
    state = await get_app_state()
    cooldowns = state.get("exit_cooldowns", {})
    if symbol in cooldowns:
        expiry = cooldowns[symbol]
        if datetime.now().timestamp() < expiry:
             remaining = int((expiry - datetime.now().timestamp()) / 60)
             return False, f"exit_cooldown_active_{remaining}m"

    # [QUANT] Cooldown (6 Hours)
    ts_map = state.get("last_trade_ts_map", {})
    # Check if ANY strategy traded this symbol in last 6 hours
    for key, last_ts in ts_map.items():
        if symbol in key:
            if (datetime.now().timestamp() - last_ts) < PER_SYMBOL_COOLDOWN_SEC:
                return False, "symbol_cooldown"

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

async def register_trade_close(pnl, symbol):
    state = await get_app_state()
    
    # [QUANT] Set 3-Hour Cooldown
    cooldowns = state.get("exit_cooldowns", {})
    # Expire in 3 hours (10800 seconds)
    cooldowns[symbol] = datetime.now().timestamp() + (3 * 3600)
    await db.set_state_key("exit_cooldowns", cooldowns)

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

# [HARDENING] Pre-Buy Sanity Checks
def buy_sanity_check(symbol, price, qty, usd, sl, tp):
    if price <= 0 or qty <= 0: return False, "invalid_price_or_qty"
    if usd < 5.0: return False, "order_value_too_low"
    if sl > 0 and sl >= price: return False, f"invalid_sl_direction (SL: {sl}, Price: {price})"
    if tp > 0 and tp <= price: return False, f"invalid_tp_direction (TP: {tp}, Price: {price})"
    return True, "ok"

# ------------------------------------------------------------------------------
# [SAFETY] Portfolio Sync
# ------------------------------------------------------------------------------
async def sync_portfolio_with_exchange():
    """
    Checks if DB open trades actually exist on Binance.
    Deletes them if they are phantom (phantom = DB has it, Exchange doesnt).
    """
    if TRADE_MODE != "live":
        return

    try:
        # 1. Fetch DB State
        db_trades = await db.get_open_trades()
        if not db_trades: return
        
        # 2. Fetch Exchange State
        bal = await ex_live.fetch_balance()
        total = bal.get('total', {})
        
        # 3. Compare and Prune
        for t in db_trades:
            coin = t['symbol'].split('/')[0]
            db_qty = t['qty']
            real_qty = total.get(coin, 0.0)
            
            # [HARDENING] Strict Phantom Detection with Dust Consideration
            # Rule: If Binance holding is effectively zero (< 1e-8) OR only dust remains (< 5% of DB qty),
            # treat it as a closed position (phantom).
            if real_qty <= 1e-8 or real_qty < (db_qty * 0.05):
                logger.warning(f"[SYNC] PHANTOM/DUST DETECTED: {t['symbol']} (DB: {db_qty} | Real: {real_qty}). Closing in DB.")
                
                # [FIX] Do not delete. Preserve history. Mark as closed with 0 PnL.
                # Use temporary connection for safety as before.
                import aiosqlite
                async with aiosqlite.connect("trades.db") as conn:
                    await conn.execute("""
                        UPDATE trades 
                        SET status='closed', exit_time=?, pnl=0, exit_price=0, fees_usd=0 
                        WHERE id=?
                    """, (datetime.now(timezone.utc).isoformat(), t['id']))
                    await conn.commit()
            
    except Exception as e:
        logger.error(f"[SYNC] Error syncing portfolio: {e}")

# ------------------------------------------------------------------------------

# EXECUTION & ORDER MANAGEMENT
# ------------------------------------------------------------------------------
async def execute_buy(symbol, sl_pct, tp_pct, strategy):
    await daily_reset_if_needed()
    
    # [DYNAMIC] Calculate optimal trade size based on current capital (ONCE)
    equity, locked, free, _, _ = await get_equity_locked_free()
    open_trades = await db.get_open_trades()
    _, calculated_trade_usd = calculate_position_limits(equity, locked, free, len(open_trades))
    
    # [FIX] Prioritize User Override over Dynamic Calculation
    state = await get_app_state()
    user_override = state.get("trade_usd")
    if user_override:
        trade_usd = float(user_override)
    else:
        trade_usd = calculated_trade_usd
    
    # Cap trade size at free balance with 2% buffer for fees
    usd = min(trade_usd, free * 0.98)
    
    if usd < 5: return # Too small
    
    if not await symbol_exposure_ok(symbol, usd): return
    ok, reason = await can_place_trade(symbol, usd, strategy, equity, locked, free)
    if not ok:
        logger.info(f"[BUY SKIP] {symbol}: {reason}")
        return

    ticker = await safe_fetch_ticker(symbol)
    if not ticker: return
    
    price = num(ticker["last"])
    
    # Execution
    if TRADE_MODE == "live":
        try:
            # [HARDENING] Sanity check before order
            sl = safe(price * (1 - sl_pct / 100)) if sl_pct else 0.0
            tp = safe(price * (1 + tp_pct / 100)) if tp_pct else 0.0
            qty_pre = usd / price
            
            ok, msg = buy_sanity_check(symbol, price, qty_pre, usd, sl, tp)
            if not ok:
                logger.error(f"❌ [SANITY CANCEL] {symbol}: {msg}")
                return

            # [HARDENING] Move load_markets to startup and remove here
            amount = num(ex_live.amount_to_precision(symbol, qty_pre))
            
            order = await ex_live.create_market_buy_order(symbol, amount)
            # Success: reset global error counter
            global consecutive_api_errors
            async with err_lock:
                consecutive_api_errors = 0
            
            exec_price = num(order.get("average") or order.get("price") or price)
            qty = num(order.get("filled") or 0)
            # ... rest of the extraction logic ...
            if qty <= 0:
                try:
                    order = await ex_live.fetch_order(order['id'], symbol)
                    qty = num(order.get("filled") or 0)
                    exec_price = num(order.get("average") or order.get("price") or price)
                except: pass
            
            # [HARDENING] Validate Trade Reality
            # If exchange gave us 0 qty or < $5 value, DO NOT TRACK IT.
            # This prevents 0-qty "Phantom Trades" from hitting the DB.
            if qty <= 1e-8 or safe(exec_price * qty) < 5.0:
                 logger.error(f"❌ [PHANTOM BUY DETECTED] {symbol}: Qty {qty}, Cost {safe(exec_price * qty)}. Aborting DB insert.")
                 return

            used = safe(exec_price * qty)
            logger.info(f"✅ [TRADE OPEN] {strategy} | {symbol} @ {exec_price} | Qty: {qty} | SL: {sl} | TP: {tp}")

            # Fee handling
            fee_obj = order.get('fee')
            if fee_obj and fee_obj.get('cost') is not None:
                fee_cost = num(fee_obj['cost'])
                fee_currency = fee_obj.get('currency')
                if fee_currency and fee_currency == symbol.split('/')[0]:
                    fees = safe(fee_cost * exec_price)
                else:
                    fees = safe(fee_cost)
            else:
                fees = safe(used * COMMISSION_PCT)
        except Exception as e:
            async with err_lock:
                consecutive_api_errors += 1
            logger.error(f"❌ [BUY FAIL] {symbol}: {e}")
            return
    else:
        # Paper
        exec_price = price
        qty = safe(usd / price)
        used = safe(qty * exec_price)
        fees = safe(used * COMMISSION_PCT)
        sl = safe(exec_price * (1 - sl_pct / 100)) if sl_pct else 0.0
        tp = safe(exec_price * (1 + tp_pct / 100)) if tp_pct else 0.0
        logger.info(f"📑 [PAPER OPEN] {strategy} | {symbol} @ {exec_price} | Qty: {qty} | SL: {sl} | TP: {tp}")

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
                
                # [HARDENING] Check for Phantom Sell
                # If we are trying to sell but exchange says we have 0, 
                # then this DB entry is stale/phantom. Close it immediately.
                if available <= 1e-8:
                     logger.error(f"❌ [PHANTOM SELL DETECTED] {trade['symbol']}: Wallet Empty ({available}). Marking Closed.")
                     await db.update_trade(trade_id, {
                        "status": "closed", 
                        "exit_time": datetime.now(timezone.utc).isoformat(), 
                        "pnl": 0,
                        "exit_price": price
                     }) 
                     # [FIX] Registry update for consistency
                     await register_trade_close(0.0, trade['symbol'])
                     return

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
                
                # [SYNC] Fetch real fees from Binance
                fee_obj = order.get('fee')
                if fee_obj and fee_obj.get('cost') is not None:
                    fees = num(fee_obj['cost'])
                    # Fee on sell is usually USDT
                else:
                    fees = safe(exec_price * sell_qty * COMMISSION_PCT)
            except Exception as e:
                global consecutive_api_errors, pause_until_ts
                consecutive_api_errors += 1
                logger.error(f"❌ [SELL FAIL] {trade['symbol']}: {e} (Consecutive: {consecutive_api_errors})")
                if consecutive_api_errors >= 5:
                    pause_until_ts = datetime.now().timestamp() + (15 * 60)
                    logger.critical("🚨 [CRITICAL] 5+ Consecutive API Errors. Pausing for 15 mins.")
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
                # "used_usd": 0, # [FIX] Preserve used_usd for history/stats
                "exit_price": exec_price,
                "pnl": safe(trade['pnl'] + pnl),
                "fees_usd": safe(trade['fees_usd'] + fees),
                "exit_time": datetime.now(timezone.utc).isoformat()
            })
            await register_trade_close(pnl, trade['symbol'])
            logger.info(f"💰 [TRADE CLOSED] {trade['symbol']} | PnL: {pnl:.4f} | Reason: {reason}")
        else:
            await db.update_trade(trade_id, {
                "qty": remaining,
                "used_usd": safe(trade['used_usd'] * (remaining / trade['qty'])),
                "pnl": safe(trade['pnl'] + pnl),
                "fees_usd": safe(trade['fees_usd'] + fees)
            })
            logger.info(f"📉 [SELL PARTIAL] {trade['symbol']} PnL: {pnl:.4f}")
            
    except Exception as e:
        logger.exception(f"[EXECUTE SELL ERROR] {trade_id}")

# ------------------------
# LOOPS
# ------------------------
async def watcher_loop():
    logger.info("Watcher started")
    while True:
        try:
            # [HARDENING] Daily Circuit Breaker
            state = await get_app_state()
            daily_loss = state.get("daily_realized_pnl", 0.0)
            if daily_loss <= -abs(MAX_DAILY_LOSS_USD):
                if state.get("auto_trading") or not state.get("kill_switch"):
                    await db.set_state_key("auto_trading", False)
                    await db.set_state_key("kill_switch", True)
                    logger.critical(f"🛑 [CIRCUIT BREAKER] Daily Loss Limit reached (${daily_loss:.2f}). Auto-trading DISABLED. Kill-switch ACTIVE.")
            
            trades = await db.get_open_trades()
            if not trades:
                await asyncio.sleep(WATCHER_INTERVAL)
                continue

            # [HARDENING] Watcher Safety Cleanup
            # Self-Correction: If we find a trade open in DB but empty in Wallet, close it.
            # This handles manual closes via Binance App or external tools.
            try:
                bal = await ex_live.fetch_balance()
                total = bal.get('total', {})
                for t in trades:
                    coin = t['symbol'].split('/')[0]
                    real_qty = total.get(coin, 0.0)
                    # Check for Zero OR Dust (< 10% of entry qty)
                    # Note: We need t['qty'] for the ratio check
                    if real_qty <= 1e-8 or real_qty < (t['qty'] * 0.05):
                        logger.warning(f"🧹 [WATCHER CLEANUP] {t['symbol']} found empty/dust ({real_qty}). Auto-closing.")
                        await db.update_trade(t['id'], {
                            "status": "closed",
                            "exit_time": datetime.now(timezone.utc).isoformat(),
                            "pnl": 0,
                            "exit_price": 0
                        })
                        await register_trade_close(0.0, t['symbol'])
            except Exception as e:
                logger.error(f"[WATCHER CLEANUP ERROR] {e}")

            for t in trades:
                symbol = t['symbol']
                
                # Check if it was just closed by cleanup
                current_trade_check = await db.get_trade(t['id'])
                if not current_trade_check or current_trade_check['status'] != 'open':
                    continue

                # [HARDENING] Max Hold Time Enforcement
                try:
                    start_str = t['time'].replace('Z', '+00:00')
                    start_time = datetime.fromisoformat(start_str)
                    duration_sec = (datetime.now(timezone.utc) - start_time).total_seconds()
                    if duration_sec > MAX_HOLD_SECONDS:
                        logger.info(f"⏳ [TIME EXIT] {symbol} held for {int(duration_sec)}s. Closing.")
                        await execute_sell(t['id'], 100, "time_exit")
                        continue
                except Exception as e:
                    logger.error(f"Error checking hold time for {symbol}: {e}")

                ticker = await safe_fetch_ticker(symbol)
                if not ticker: continue
                price = num(ticker['last'])
                
                unreal = (price - t['entry_price']) * t['qty']
                highest = max(t['highest_price'], price)
                
                updates = {
                    "current_price": price,
                    "unrealized_pnl": safe(unreal),
                    "highest_price": highest
                }

                # [QUANT] Exit Logic Updates
                # 1. Breakeven at +1.2%
                gain_pct = ((price - t['entry_price']) / t['entry_price']) * 100
                if gain_pct >= 1.2 and t['sl'] < t['entry_price']:
                    updates['sl'] = t['entry_price']
                    logger.info(f"[BREAKEVEN] {t['symbol']} set to entry.")

                # 2. Dynamic Trailing: Activate at 2.0%, Trail 1.2%
                if not t['trail_active']:
                    if gain_pct >= 2.0: 
                        updates['trail_active'] = 1
                        updates['trail_sl'] = safe(highest * (1 - 0.012)) # 1.2% distance
                        logger.info(f"[TRAIL ON] {t['symbol']} active @ 1.2% distance")
                elif t['trail_active']:
                    new_trail = safe(highest * (1 - 0.012))
                    if new_trail > t['trail_sl']:
                        updates['trail_sl'] = new_trail

                should_close = False
                reason = ""
                
                # Check current price vs (updated) SL
                effective_sl = updates.get('sl', t['sl'])
                
                if effective_sl > 0 and price <= effective_sl:
                    should_close = True; reason = "sl"
                elif t['tp'] > 0 and price >= t['tp']:
                    should_close = True; reason = "tp"
                elif (t.get('trail_active') or updates.get('trail_active')) and price <= updates.get('trail_sl', t['trail_sl']):
                    should_close = True; reason = "trail"
                
                await db.update_trade(t['id'], updates)
                
                if should_close:
                    await execute_sell(t['id'], 100, reason)

        except Exception as e:
            logger.exception("Watcher error")
        
        await asyncio.sleep(WATCHER_INTERVAL)

# ------------------------------------------------------------------------------
# BACKGROUND LOOPS
# ------------------------------------------------------------------------------

smc_scanner_cache = [] # Global storage for SMC setups

async def strategy_loop():
    logger.info("Strategy Loop Started (Alpha Hunter + SMC)...")
    ignored = ["USDC", "USDP", "FDUSD", "TUSD", "EUR", "GBP", "DAI", 
               "SAPIEN", "DATA", "FTT", "BTTC", "GUN"] # [CLEANUP] Blacklist worst performers
    global smc_scanner_cache
    
    while True:
        try:
            # [SAFETY] Periodic Sync
            await sync_portfolio_with_exchange()
            
            state = await get_app_state()
            # [HARDENING] Full circuit breaker for Scanner
            if not state.get("auto_trading") or state.get("kill_switch"):
                await asyncio.sleep(5)
                continue
            
            # 1. Fetch all tickers
            try:
                tickers = await ex_live.fetch_tickers()
            except Exception as e:
                logger.error(f"[SCAN ERROR] Fetch tickers failed: {e}")
                await asyncio.sleep(10)
                continue

            # 2. Filter and Sort
            all_candidates = []
            for s, t in tickers.items():
                # Increased volume filter to $1M for better liquidity/stability
                if "/USDT" in s and t['quoteVolume'] > 1_000_000:
                    base = s.split('/')[0]
                    if base not in ignored:
                        all_candidates.append(t)
            
            # Sort by percentage to find Top Gainers
            all_candidates.sort(key=lambda x: float(x['percentage'] or 0), reverse=True)
            top_gainers = [t['symbol'] for t in all_candidates[:15]] # Top 15 for SMC
            others = [t['symbol'] for t in all_candidates[15:100]] # Others for Alpha
            
            # Strategy Balancing: Check current positions
            open_trades = await db.get_open_trades()
            smc_count = len([t for t in open_trades if t['strategy'] == 'smc_sniper'])
            alpha_count = len([t for t in open_trades if t['strategy'] == 'alpha_hunter'])
            
            # [DYNAMIC] Calculate and display current capital allocation
            equity, locked, free, _, _ = await get_equity_locked_free()
            max_pos, calc_trade_usd = calculate_position_limits(equity, locked, free, len(open_trades))
            utilization = (locked / equity * 100) if equity > 0 else 0
            
            # [VISIBILITY] Alert if significant capital is idle
            if equity > 0 and (free / equity) > 0.25:
                logger.info(
                    f"⚠️ [CAPITAL IDLE] {free:.2f} USDT free "
                    f"({free/equity*100:.1f}%) — likely due to regime, cooldown, or limits"
                )
            
            logger.info(f"🔍 [SCANNER] Cycle: SMC on {len(top_gainers)} gainers, Alpha on {len(others)} pairs.")
            logger.info(f"📊 [STATUS] Positions: {len(open_trades)}/{max_pos} | Capital: ${locked:.0f}/${equity:.0f} ({utilization:.1f}%) | Next Trade: ${calc_trade_usd:.0f}")
            
            # 3. SMC Scan (Top Gainers) - Population ONLY (No Trading in Ph2)
            new_smc_cache = []
            for symbol in top_gainers:
                try:
                    ohlcv = await ex_live.fetch_ohlcv(symbol, '15m', limit=100)
                    
                    # [QUANT] Calculate Trend (1h Context)
                    # We need 1h candles to check the trend. Since we have 15m candles here for SMC,
                    # we do a separate fetch for 1h trend context.
                    trend_bullish = True
                    try:
                         ohlcv_1h = await ex_live.fetch_ohlcv(symbol, '1h', limit=60)
                         df_1h = pd.DataFrame(ohlcv_1h, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                         ema50 = df_1h['close'].ewm(span=50, adjust=False).mean().iloc[-1]
                         current_price = df_1h['close'].iloc[-1]
                         trend_bullish = current_price > ema50
                    except:
                        pass # Default to True (permissive) if trend fetch fails to allow fallback to other checks

                    # We call check_signal to populate diagnostics for near_hits/dashboard
                    # Now passing trend_bullish status to force trend alignment
                    _, diagnostic = SMCManager.check_signal(symbol, ohlcv, trend_bullish=trend_bullish)
                    
                    if diagnostic:
                        diagnostic['time'] = datetime.now(timezone.utc).isoformat()
                        near_hits.insert(0, diagnostic)
                        while len(near_hits) > 20: near_hits.pop()

                    # Update Scanner Cache for UI visibility
                    scanner_data = SMCManager.get_scanner_data(symbol, ohlcv)
                    if scanner_data: new_smc_cache.extend(scanner_data)
                    
                    # [QUANT] SMC Sniper Execution (Enabled)
                    is_valid_signal, _ = SMCManager.check_signal(symbol, ohlcv, trend_bullish=trend_bullish)
                    if is_valid_signal:
                        # SMC typically aims for high RR. 
                        # Using 2.0% SL and 6.0% TP (1:3 RR) as standard sniper settings.
                        await execute_buy(symbol, 2.0, 6.0, "SMC_SNIPER")
                    
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"[SMC ERROR] {symbol}: {e}")
            
            smc_scanner_cache = sorted(new_smc_cache, key=lambda x: abs(x['distance_pct']))[:20]

            # 4. AlphaHunter Scan (Others)
            for symbol in others:
                if not state.get("auto_trading"): break
                try:
                    ohlcv = await ex_live.fetch_ohlcv(symbol, '1h', limit=25)
                    signal, diagnostic = AlphaHunter.check_signal(symbol, ohlcv)
                    
                    if diagnostic:
                        diagnostic['time'] = datetime.now(timezone.utc).isoformat()
                        near_hits.insert(0, diagnostic)
                        while len(near_hits) > 20: near_hits.pop()

                    if signal:
                        # [QUANT] Expectancy Control (RRR >= 1.8)
                        tp_val = diagnostic.get('tp_pct', 0.0)
                        sl_val = 6.0 # Existing SL for AlphaHunter
                        if tp_val >= (sl_val * 1.8):
                            await execute_buy(symbol, sl_val, tp_val, "alpha_hunter")
                            alpha_count += 1
                        else:
                            logger.info(f"[EXPECTANCY SKIP] {symbol} RRR too low ({tp_val}/{sl_val})")
                    
                    # [QUANT] Bollinger Reversion Integration (Low Frequency)
                    sig_bb = bollinger_entry_ok(symbol, ohlcv)
                    if sig_bb:
                        logger.info(f"[BB SIGNAL] {symbol} oversold reversion!")
                        # Tight 2% SL, 4% TP for Bollinger (RRR = 2.0 > 1.8)
                        await execute_buy(symbol, 2.0, 4.0, "bollinger_reversion")

                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"[ALPHA ERROR] {symbol}: {e}")

            logger.info("[SCANNER] Cycle complete.")
            
        except Exception as e:
            logger.exception("Strategy loop crashed")
        
        await asyncio.sleep(60 * 5)

# ------------------------------------------------------------------------------
# FASTAPI ENDPOINTS
# ------------------------------------------------------------------------------
@app.get("/stats")
async def stats():
    equity, locked, free, api_status, api_error = await get_equity_locked_free()
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

        "total_trades": len(closed),
        "api_status": api_status,
        "api_error": api_error
    }

@app.get("/trades")
async def get_trades():
    return await db.get_all_trades_desc()

@app.get("/positions")
async def get_positions():
    # [HARDENING] Sync before returning to ensure frontend is 100% accurate
    await sync_portfolio_with_exchange()
    return await db.get_open_trades()

@app.get("/signals")
async def get_signals():
    return near_hits

@app.get("/smc-scanner")
async def get_smc_scanner():
    return smc_scanner_cache

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
    logger.info(f"[ADMIN] Updating trade_usd to ${amount}")
    await db.set_state_key("trade_usd", float(amount))
    return {"status": "ok"}
