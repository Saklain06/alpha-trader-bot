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
from logic.strategy import StrategyManager
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
    "timeout": 20000, 
    "options": {
        "defaultType": "spot",
        "adjustForTimeDifference": True,
        "recvWindow": 60000
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
MAX_HOLD_SECONDS = 8 * 3600
MAX_FLAT_PNL_PCT = 0.5
WATCHER_INTERVAL = 5
STRATEGY_INTERVAL = 60 # Check every minute
MIN_CLOSE_QTY_PCT = 0.15
COMMISSION_PCT = float(os.environ.get("COMMISSION_PCT", "0.001"))
DEFAULT_SLIPPAGE_PCT = float(os.environ.get("DEFAULT_SLIPPAGE_PCT", "0.001"))

MAX_ORDER_USD = float(os.environ.get("MAX_ORDER_USD", "120.0"))

# [QUANT UPDATES] Low frequency, High quality
MAX_POSITION_COUNT = int(os.environ.get("MAX_POSITION_COUNT", "12"))
MAX_TRADES_PER_DAY = 30
PER_SYMBOL_COOLDOWN_SEC = 1 * 3600 # 1 Hour
MAX_BOLLINGER_POSITIONS = 1
near_hits = [] # Global storage for interesting setups
smc_scanner_cache = [] # Cache for frontend scanner

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
# GLOBAL STATE
# ------------------------
cached_regime = {"value": "neutral", "ts": 0, "multiplier": 0.5}
partial_taken_cache = set() # Stores IDs of trades that have taken partials
market_trend_score = 50
market_trend_label = "Neutral"

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
    """
    Returns (regime_label, risk_multiplier)
    Standardized to match the Strong Trend Strategy rules.
    """
    is_bullish, price, ema_50 = await regime_utils.check_market_regime(ex_live)
    label = "bullish" if is_bullish else "bearish"
    multiplier = 1.0 if is_bullish else 0.0
    return label, multiplier


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
        await db.set_state_key("daily_losses_count", 0)
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

    # [QUANT] 3-State Regime Filter - REMOVED (User Request)
    
    # [QUANT] 3-Hour Post-Exit Cooldown

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
    
    # [QUANT] Set 1-Hour Cooldown
    cooldowns = state.get("exit_cooldowns", {})
    # Expire in 1 hour (3600 seconds)
    cooldowns[symbol] = datetime.now().timestamp() + (1 * 3600)
    await db.set_state_key("exit_cooldowns", cooldowns)

    # Daily PnL
    daily = state.get("daily_realized_pnl", 0.0) + pnl
    await db.set_state_key("daily_realized_pnl", daily)
    
    # [QUANT] Count Losses - REMOVED
    
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
                # [RACE CONDITION FIX] Re-check DB status before closing
                current_db_trade = await db.get_trade(t['id'])
                if not current_db_trade or current_db_trade['status'] != 'open':
                    # Trade was likely closed by execute_sell while we were fetching balance
                    continue

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
async def execute_buy(symbol, sl_pct, tp_pct, strategy, sl_absolute=None, btc_multiplier=1.0):
    await daily_reset_if_needed()
    
    ticker = await safe_fetch_ticker(symbol)
    if not ticker: return
    price = num(ticker["last"])
    
    # [QUANT] 1. Calculate Risk Distance
    if sl_absolute is not None:
        sl = sl_absolute
        if sl >= price: 
            logger.warning(f"[BUY SKIP] Invalid Absolute SL {sl} >= Price {price}")
            return
        sl_dist_usd = price - sl
        sl_pct_calc = (sl_dist_usd / price) * 100
    elif sl_pct is not None:
        sl_dist_usd = price * (sl_pct / 100)
        sl = price - sl_dist_usd
    else:
        logger.error(f"[BUY FAIL] {symbol}: No SL provided (Absolute or %).")
        return
    
    # [QUANT] 2. Position Sizing (Risk 2% of Equity * BTC Regime)
    equity, locked, free, _, _ = await get_equity_locked_free()
    
    BASE_RISK = 0.02 # 2% (Modified for Growth)
    final_risk_pct = BASE_RISK * btc_multiplier
    risk_amount = equity * final_risk_pct
    
    # Qty = Risk / Distance
    if sl_dist_usd > 0:
        target_qty = risk_amount / sl_dist_usd
        risk_based_usd = target_qty * price
    else:
        # Fallback if SL is 0 
        risk_based_usd = 20.0 
        
    # [QUANT] 3. Apply Limits
    state = await get_app_state()
    user_cap_usd = float(state.get("trade_usd", 20.0))
    
    # [RULE] Harmonized Sizing Logic
    # We take the SMALLEST of three values:
    # 1. Risk-Based Size (Calculated to lose 2%)
    # 2. User Safety Cap (From Control Panel)
    # 3. 50% of Equity (Blow-up Prevention)
    
    equity_cap = equity * 0.50
    
    # Calculate Final Size
    usd = min(risk_based_usd, user_cap_usd, equity_cap, free * 0.98)
    
    # Log if we are being capped by safety rules
    if usd < risk_based_usd:
         reason = "User Cap" if usd == user_cap_usd else "50% Portfolio Limit"
         logger.info(f"🛡️ [SAFETY RESIZE] {symbol}: RiskSize ${risk_based_usd:.2f} -> Capped at ${usd:.2f} ({reason})")
    
    logger.info(f"⚖️ [SIZING] {symbol} | Risk: {final_risk_pct*100:.1f}% (${risk_amount:.2f}) | Size: ${usd:.2f}")

    if usd < 5: 
        logger.info(f"[BUY SKIP] {symbol}: Size ${usd:.2f} too small")
        return # Too small
    
    if not await symbol_exposure_ok(symbol, usd): return
    ok, reason = await can_place_trade(symbol, usd, strategy, equity, locked, free)
    if not ok:
        logger.info(f"[BUY SKIP] {symbol}: {reason}")
        return

    # [RULE] Fixed Risk : Reward = 1 : 2
    # TP = Entry + (2 * SL Distance)
    if sl_dist_usd > 0:
        tp_price = price + (2 * sl_dist_usd)
        tp = num(tp_price)
        logger.info(f"🎯 [TP CALC] 1:2 RR -> Profit Target @ {tp}")
    else:
        tp = 0.0

    # ... (ticker fetch was moved up)
    
    # Execution
    if TRADE_MODE == "live":
        try:
            # [HARDENING] Sanity check before order
            # SL is already calculated above
            # TP is calculated above (1:2 fixed)
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
            # [HARDENING] Daily Circuit Breaker - REMOVED
            
            trades = await db.get_open_trades()
            if not trades:
                await asyncio.sleep(WATCHER_INTERVAL)
                continue

            # [HARDENING] Watcher Safety Cleanup
            # If we find a trade open in DB but empty in Wallet, close it.
            try:
                bal = await ex_live.fetch_balance()
                total = bal.get('total', {})
                for t in trades:
                    coin = t['symbol'].split('/')[0]
                    real_qty = total.get(coin, 0.0)
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
                try:
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
                    except: pass

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
                    
                    # -----------------------------------------------
                    # STOP LOSS & TAKE PROFIT CHECKS (UNIVERSAL)
                    # -----------------------------------------------
                    t_sl = t.get('sl', 0.0)
                    t_tp = t.get('tp', 0.0)
                    
                    if t_sl > 0 and price <= t_sl:
                         logger.info(f"🛑 [SL HIT] {symbol} @ {price} (SL: {t_sl})")
                         await db.update_trade(t['id'], updates)
                         await execute_sell(t['id'], 100, "stop_loss")
                         continue
                    
                    if t_tp > 0 and price >= t_tp:
                         logger.info(f"🎯 [TP HIT] {symbol} @ {price} (TP: {t_tp})")
                         await db.update_trade(t['id'], updates)
                         await execute_sell(t['id'], 100, "take_profit")
                         continue

                    # [RULE] No trailing stop or partial exits.
                    # Simple update of PnL stats.
                    await db.update_trade(t['id'], updates)

                except Exception as e:
                    logger.error(f"[WATCHER ERROR] {t['symbol']}: {e}")
            
            await asyncio.sleep(WATCHER_INTERVAL)

        except Exception as e:
            logger.exception("Watcher error")
        
        await asyncio.sleep(WATCHER_INTERVAL)

# ------------------------------------------------------------------------------
# BACKGROUND LOOPS
# ------------------------------------------------------------------------------


# ------------------------
# PARALLEL SCANNERS
# ------------------------
scan_sem = asyncio.Semaphore(10) # Limit concurrent requests

async def scan_smc_target(symbol, ex, active_strategies):
    """
    Returns: (symbol, scanner_items, diagnostic, should_buy, bullish_trend_found)
    """
    async with scan_sem:
        try:
            # 1. [CONTEXT] Fetch 1h for Directional Bias (Higher TF)
            ohlcv_context = await ex.fetch_ohlcv(symbol, '1h', limit=100)
            if not ohlcv_context or len(ohlcv_context) < 50: return (symbol, None, None, False, False)
            
            df_context = pd.DataFrame(ohlcv_context, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            
            # [STRATEGY] Calculate Symbol 24H Change for Context
             # Helper to calc 24h change Approx (24 candles)
            try:
                open_24h = df_context['open'].iloc[-25] if len(df_context) >= 25 else df_context['open'].iloc[0]
                curr_close = df_context['close'].iloc[-1]
                symbol_pct_change = ((curr_close - open_24h) / open_24h) * 100
            except: symbol_pct_change = 0.0

            # Context Analysis
            trend_bullish = True 

            
            # 1h RSI (REMOVED)
            # [USER REQUEST] RSI logic completely removed.
            
            context = {
                "trend_bullish": trend_bullish,
                "ohlcv_1h": ohlcv_context, # Pass raw data for HTF OB analysis
                "symbol_pct_change": symbol_pct_change, # [NEW]
                "btc_pct_change": active_strategies.get("btc_pct", 0.0) if isinstance(active_strategies, dict) else 0.0 # Hacky pass
            }

            # 2. [ENTRY] Fetch 15m for Entry (Strong Trend Strategy)
            ohlcv_entry = await ex.fetch_ohlcv(symbol, '15m', limit=100)
            if not ohlcv_entry or len(ohlcv_entry) < 60:
                logger.warning(f"[DEBUG] {symbol} not enough 15m data: {len(ohlcv_entry) if ohlcv_entry else 0}")
                return (symbol, None, None, False, False)
            
            # 3. Check Signal with Multi-Timeframe Logic
            is_valid_signal, diagnostic = StrategyManager.check_signal(symbol, ohlcv_entry, context)
            
            # Enrich diagnostic with Context
            if diagnostic:
                diagnostic['trend_1h'] = "Bullish" # Always True now
            
            # Get Scanner Data (Visuals)
            # Pass CONTEXT so we can visualize the HTF OB (Entry Zone)
            scanner_data = StrategyManager.get_scanner_data(symbol, ohlcv_entry, context)
            
            if scanner_data:
                # [VISUALS] Compute Volatility for Dashboard
                df_entry = pd.DataFrame(ohlcv_entry, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                v_ok, v_msg = check_volatility_ok(df_entry, '15m')
                
                for item in scanner_data:
                    item['trend'] = "Bullish" 
                    item['vol_ok'] = v_ok
                    item['vol_msg'] = v_msg
            
            return (symbol, scanner_data, diagnostic, is_valid_signal, trend_bullish)

        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}")
            return (symbol, None, None, False, False)


async def strategy_loop():
    logger.info("Strategy Loop Started (Parallelized V2)...")
    ignored = ["USDC", "USDP", "FDUSD", "TUSD", "EUR", "GBP", "DAI", 
               "SAPIEN", "DATA", "FTT", "BTTC", "GUN"] 
    global smc_scanner_cache
    global market_trend_score, market_trend_label
    
    while True:
        try:
            start_ts = datetime.now()
            logger.info(f"[DEBUG] Loop Cycle Start {start_ts}")
            # [SAFETY] Periodic Sync
            await sync_portfolio_with_exchange()
            
            # [RESET] Check for new day immediately
            await daily_reset_if_needed()
            
            state = await get_app_state()
            if not state.get("auto_trading") or state.get("kill_switch"):
                await asyncio.sleep(5)
                continue
                
            # [SAFETY] Daily Loss Count Limit - REMOVED
            
            # [OPTIMIZATION] Time Filter: Avoid Late NY (Death Zone)
            # 17:00 - 20:00 UTC (User stats show -33% WR / Negative PnL here)
            now_utc = datetime.now(timezone.utc)
            if 17 <= now_utc.hour < 20:
                 logger.warning(f"💤 [TIME FILTER] Late NY Session ({now_utc.strftime('%H:%M')} UTC). Sleeping until 20:00 UTC.")
                 smc_scanner_cache = []
                 await asyncio.sleep(60)
                 continue
            
            # [STRATEGY RESET] 1. Market Regime - REMOVED (User Request)
            # We assume Bullish unless Time Filter hits.
            market_trend_label = "Bullish"
            market_trend_score = 100
            
            # 1. Fetch all tickers
            try:
                tickers = await ex_live.fetch_tickers()
            except Exception as e:
                logger.error(f"[SCAN ERROR] Fetch tickers failed: {e}")
                await asyncio.sleep(10)
                continue

            # 2. Filter and Sort
            all_candidates = []
            
            # [STRATEGY] Fetch BTC % Change for Relative Strength Comparison
            btc_ticker = await safe_fetch_ticker("BTC/USDT")
            btc_pct = float(btc_ticker['percentage'] or 0) if btc_ticker else 0
            
            for s, t in tickers.items():
                if "/USDT" in s:
                    base = s.split('/')[0]
                    if base not in ignored and s != 'BTC/USDT':
                        # [STRATEGY] Relative Strength Filter (24h Change)
                        # Pick assets outperforming BTC over the last 24h
                        asset_pct = float(t['percentage'] or 0)
                        if asset_pct > btc_pct:
                             all_candidates.append(t)
            
            all_candidates.sort(key=lambda x: float(x['percentage'] or 0), reverse=True)
            top_gainers = [t['symbol'] for t in all_candidates[:35]] # Focus on Top 35 Leaders 
            
            open_trades = await db.get_open_trades()
            active_strats = [t['strategy'] for t in open_trades] # Not strictly needed inside scan, but good for context if needed later
            
            # ---------------------------------------------------------
            # MARKET INTELLIGENCE (Aligned with Trading Logic)
            # ---------------------------------------------------------
            # [FIX] Use already calculated regime
            btc_regime = "bullish" if is_bullish_regime else "bearish"
            btc_multiplier = 1.0 if is_bullish_regime else 0.0
            
            # ---------------------------------------------------------
            # PARALLEL EXECUTION: SMC
            # ---------------------------------------------------------
            
            # [RULE] Global Market Condition: BTC 1H Candle Range > 2%
            # If (High - Low) / Open > 0.02, BLOCK ALL TRADES
            try:
                 btc_candles = await ex_live.fetch_ohlcv("BTC/USDT", "1h", limit=5)
                 if btc_candles:
                     last_btc = btc_candles[-1] # [ts, o, h, l, c, v]
                     # Check range
                     rng = (last_btc[2] - last_btc[3]) / last_btc[1]
                     if rng > 0.02:
                         logger.warning(f"🛑 [VOLATILITY BLOCK] BTC 1H Range {rng*100:.2f}% > 2%. Stopping Scan.")
                         # Clear candidates to skip
                         top_gainers = []
            except Exception as e:
                logger.error(f"[BTC CHECK FAIL] {e}")

            # Context Object for passing BTC data
            scan_context = {"btc_pct": btc_pct}

            # We fetch all candidates in parallel
            smc_tasks = [scan_smc_target(s, ex_live, scan_context) for s in top_gainers]
            smc_results = await asyncio.gather(*smc_tasks)
            
            new_smc_cache = []
            bullish_count = 0
            
            # Process SMC Results (Sequential Execution for safety)
            for res in smc_results:
                sym, data, diag, sig, is_bullish = res
                
                if is_bullish: bullish_count += 1
                if data: 
                    new_smc_cache.extend(data)
                
                if diag:
                    diag['time'] = datetime.now(timezone.utc).isoformat()
                    near_hits.insert(0, diag)
                
                if sig:
                    # Execute Trade (Sequential, Safe)
                    sl_abs = diag.get('sl')
                    trigger_type = diag.get('trigger', 'SMC')
                    strategy_name = f"SMC_{trigger_type}"
                    
                    if btc_multiplier > 0:
                        await execute_buy(sym, None, None, strategy_name, sl_absolute=sl_abs, btc_multiplier=btc_multiplier)
                    else:
                        logger.info(f"🛑 [REGIME BLOCK] {sym}: Signal ignored due to Bearish BTC Regime")
                
            # [FIX] Also Scan Active Positions for Dashboard Visualization
            active_symbols = [t['symbol'] for t in open_trades]
            missing_active = [s for s in active_symbols if s not in top_gainers]
            
            if missing_active:
                active_res = await asyncio.gather(*[scan_smc_target(s, ex_live, active_strats) for s in missing_active])
                for res in active_res:
                    _, data, _, _, _ = res
                    if data: new_smc_cache.extend(data)
            
            # Update Global Cache
            smc_scanner_cache = new_smc_cache[:20]
            while len(near_hits) > 20: near_hits.pop()

            # UI SYNC
            if len(top_gainers) > 0:
                raw = int((bullish_count / len(top_gainers)) * 100)
                
                if btc_regime == "bearish":
                    market_trend_score = min(raw, 20) 
                    market_trend_label = "Bearish"
                elif btc_regime == "neutral":
                    market_trend_score = min(raw, 50) 
                    market_trend_label = "Neutral"
                else:
                    market_trend_score = raw
                    market_trend_label = "Bullish"
            
            logger.info(f"📈 [MARKET TREND] Score: {market_trend_score}/100 ({market_trend_label}) | Regime: {btc_regime} ({btc_multiplier}x)")

            # ---------------------------------------------------------
            # END OF LOOP
            # ---------------------------------------------------------
            duration = (datetime.now() - start_ts).total_seconds()
            logger.info(f"[SCANNER] Cycle complete in {duration:.2f}s.")
            
        except Exception as e:
            logger.exception("Strategy loop crashed")
        
        await asyncio.sleep(60)


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
    total_unrealized_pnl = sum((t.get('unrealized_pnl') or 0.0) for t in open_trades)
    
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
        "api_error": api_error,
        
        # [MARKET INTELLIGENCE]
        "market_trend_score": market_trend_score,
        "market_trend_label": market_trend_label,
        
        # [CIRCUIT BREAKER] - DISABLED
        "circuit_breaker_triggered": False, # state.get("daily_losses_count", 0) >= MAX_DAILY_LOSING_TRADES,
        "reset_time_ts": int(datetime.now().replace(hour=23, minute=59, second=59, microsecond=0).timestamp() * 1000)
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

@app.get("/history")
async def get_history(symbol: str, interval: str = "15m"):
    """Fetch primitive OHLCV history for custom charts"""
    try:
        if symbol.lower() == "btc/usdt":
             ohlcv = await ex_live.fetch_ohlcv(symbol, interval, limit=200)
        else:
             # Use the same exchange instance as strategy
             ohlcv = await ex_live.fetch_ohlcv(symbol, interval, limit=200)
             

        # Convert to Pandas for Indicators
        df_hist = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
        df_hist['ema5'] = df_hist['close'].ewm(span=5, adjust=False).mean() # [NEW] EMA 5
        df_hist['ema50'] = df_hist['close'].ewm(span=50, adjust=False).mean()

        # [NEW] Simple RSI Calc
        delta = df_hist['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss.replace(0, 0.0001))
        df_hist['rsi'] = 100 - (100 / (1 + rs))

        candles = []
        ema5 = [] # [NEW]
        ema50 = []
        rsi = []

        for i, row in df_hist.iterrows():
            t_sec = int(row['time'] / 1000)
            candles.append({
                "time": t_sec, 
                "open": row['open'],
                "high": row['high'],
                "low": row['low'],
                "close": row['close']
            })
            
            if not pd.isna(row['ema5']):
                ema5.append({"time": t_sec, "value": row['ema5']})
            if not pd.isna(row['ema50']):
                ema50.append({"time": t_sec, "value": row['ema50']})
            if not pd.isna(row['rsi']):
                rsi.append({"time": t_sec, "value": row['rsi']})

        return {
            "candles": candles,
            "ema20": ema5, # Hack: Send EMA 5 in the "ema20" slot for now to keep frontend working
            "ema5": ema5,  # Send correct key too for future update
            "ema50": ema50,
            "rsi": rsi
        }
    except Exception as e:
        logger.error(f"History fetch error: {e}")
        return {"candles": [], "ema20": [], "ema50": [], "rsi": []}

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
