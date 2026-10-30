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


# Third-Party Imports
import pandas as pd
# import numpy as np # Unused
from dotenv import load_dotenv
import ccxt.async_support as ccxt
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from database import db
from logic.strategy import StrategyManager
from logic.indicators import check_volatility_ok
from logic.agent_gate import AgentGate

# Auth Imports
from fastapi import Depends, HTTPException, status
import aiosqlite # for auth lookup

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

# File Handler with Rotation (10MB, keep 5, UTF-8 for emoji logs on Windows)
file_handler = RotatingFileHandler("server.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# Stream Handler (Stdout)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# ------------------------
# LIVE / PAPER MODE
# ------------------------
TRADE_MODE = os.environ.get("TRADE_MODE", "paper")
logger.info(f"TRADE_MODE: {TRADE_MODE}")

# ------------------------
# EXCHANGE (ASYNC)
# ------------------------
exchange_config = {
    "enableRateLimit": True,
    "timeout": 20000, 
    "options": {
        "defaultType": "spot",
        "adjustForTimeDifference": True,
        "recvWindow": 60000,
        "fetchCurrencies": False,  # Avoids geo-restricted sapi calls during load_markets()
    }
}
# Only attach trading keys if in live mode to avoid IP restriction errors on public endpoints
if TRADE_MODE == "live" and os.getenv("BINANCE_API_KEY"):
    exchange_config["apiKey"] = os.getenv("BINANCE_API_KEY")
    exchange_config["secret"] = os.getenv("BINANCE_SECRET_KEY")

ex_live = ccxt.binance(exchange_config)

# In paper mode (or cloud environments), route public market data through Binance's global unblocked endpoint
if TRADE_MODE != "live":
    for _k, _v in list(ex_live.urls.get("api", {}).items()):
        if isinstance(_v, str) and "api.binance.com" in _v and _k in ("public", "v1", "v3"):
            ex_live.urls["api"][_k] = _v.replace("https://api.binance.com", "https://data-api.binance.vision")

# ------------------------------------------------------------------------------
# CONFIG & CONSTANTS
# ------------------------------------------------------------------------------
STRATEGY_SMC_5EMA = "SMC_5EMA_Reclaim"
STRATEGY_NAME = STRATEGY_SMC_5EMA
AUTO_TRADING_ENABLED = True
BASE_BALANCE = float(os.environ.get("BASE_BALANCE", "800.0"))

MAX_SYMBOL_EXPOSURE_USD = float(os.environ.get("MAX_SYMBOL_EXPOSURE_USD", "2000.0"))
MAX_HOLD_SECONDS = 24 * 3600
MAX_FLAT_PNL_PCT = 0.5
WATCHER_INTERVAL = 1
STRATEGY_INTERVAL = 15 # Scan Top 20 Gainers every 15 seconds for live 0.146 touch
MIN_CLOSE_QTY_PCT = 0.15
COMMISSION_PCT = float(os.environ.get("COMMISSION_PCT", "0.001"))
DEFAULT_SLIPPAGE_PCT = float(os.environ.get("DEFAULT_SLIPPAGE_PCT", "0.001"))

MAX_ORDER_USD = float(os.environ.get("MAX_ORDER_USD", "2000.0"))

# [STRATEGY] Capital-First v1 Constants
ALLOWED_SYMBOLS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 
    'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'NEAR/USDT', 'DOT/USDT'
]
DAILY_LOSS_LIMIT_R = -4.0
STRATEGY_DEATH_LIMIT_R = -100.0

# [QUANT UPDATES] 2-Slot Concentrated High-Conviction Execution ($400/slot base, +30% step-up)
MAX_POSITION_COUNT = int(os.environ.get("MAX_POSITION_COUNT", "2"))
MAX_TRADES_PER_DAY = 9999 # [SCALPER] Unlimited trades
PER_SYMBOL_COOLDOWN_SEC = 0 # Handled by "Max 3 trades per coin" check

near_hits = [] # Global storage for interesting setups
smc_scanner_cache = [] # Cache for frontend scanner

# [HARDENING] Global Safety State

consecutive_api_errors = 0
pause_until_ts = 0
err_lock = asyncio.Lock()
scanner_semaphore = asyncio.Semaphore(10) # [NEW] Prevent bursting too many connections
last_market_reload = 0 # [NEW] Track market refresh

def min_notional_ok(symbol, usd):
    market = ex_live.markets.get(symbol)
    if not market:
        return False

    limits = market.get("limits", {})
    cost_min = limits.get("cost", {}).get("min", 0)

    return usd >= cost_min


last_loop_ts = None
last_loop_error = None
last_top_gainers = []

@app.get("/api/debug-status")
async def debug_status():
    return {
        "server_time": datetime.now(timezone.utc).isoformat(),
        "last_loop_ts": str(last_loop_ts),
        "last_loop_error": str(last_loop_error),
        "last_top_gainers_count": len(last_top_gainers),
        "last_top_gainers": last_top_gainers[:5],
        "scanner_cache_count": len(smc_scanner_cache),
        "near_hits_count": len(near_hits),
        "market_trend_score": market_trend_score,
        "market_trend_label": market_trend_label,
        "consecutive_api_errors": consecutive_api_errors,
        "pause_until_ts": pause_until_ts,
    }

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

@app.middleware("http")
async def strip_api_prefix(request, call_next):
    if request.scope.get("path", "").startswith("/api/"):
        request.scope["path"] = request.scope["path"][4:] or "/"
    return await call_next(request)

# ------------------------
# AUTHENTICATION LOGIC
# ------------------------
from fastapi.security import OAuth2PasswordRequestForm
from auth import create_access_token, get_current_user, verify_password, get_password_hash
from pydantic import BaseModel

class Token(BaseModel):
    access_token: str
    token_type: str

@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    # 1. Fetch user from DB
    async with aiosqlite.connect("trades.db") as dbconn:
        dbconn.row_factory = aiosqlite.Row
        cursor = await dbconn.execute("SELECT * FROM users WHERE username = ?", (form_data.username,))
        user = await cursor.fetchone()
    
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    
    # 2. Verify Password
    if not verify_password(form_data.password, user['hashed_password']):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    
    # 3. Create Token
    access_token = create_access_token(data={"sub": user['username'], "role": user['role']})
    return {"access_token": access_token, "token_type": "bearer"}

async def get_current_admin(current_user: dict = Depends(get_current_user)):
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user

# ------------------------
# INIT DB
# ------------------------
@app.on_event("startup")
async def startup():
    await db.init_db()
    
    # Ensure default admin user exists on fresh cloud deployments
    async with aiosqlite.connect("trades.db") as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
        row = await cur.fetchone()
        if not row or row[0] == 0:
            await conn.execute(
                "INSERT INTO users (username, hashed_password, role) VALUES (?, ?, ?)",
                ("admin", "$2b$12$EiP/hnvzEMKREmJV5JLRtOF54SEOLH4b3SdugGBI/yOfSm5TiwbCS", "admin"),
            )
            await conn.commit()
            logger.info("🌱 [STARTUP] Seeded default admin user.")

    # [SAFETY] Sync DB with Exchange on Boot
    asyncio.create_task(sync_portfolio_with_exchange())
    
    # Init default state ($800 Base, 2 Slots = $400/slot)
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
        await db.set_state_key("trade_usd", 400.0)
    if "step_tier_base" not in state:
        await db.set_state_key("step_tier_base", 800.0)

    # [HARDENING] Move load_markets to startup
    try:
        await ex_live.load_markets()
        logger.info("📡 [EXCHANGE] Markets loaded successfully.")
    except Exception as e:
        logger.error(f"❌ [EXCHANGE INIT ERROR] {e}")

    asyncio.create_task(watcher_loop())
    asyncio.create_task(strategy_loop())
    asyncio.create_task(render_keepalive_loop())

async def render_keepalive_loop():
    """Pings the external Render URL every 5 minutes to prevent free-tier spin-down."""
    external_url = os.environ.get("RENDER_EXTERNAL_URL", "https://alpha-trader-bot-py42.onrender.com")
    logger.info(f"💓 [KEEPALIVE] Keepalive loop started for {external_url}")
    while True:
        await asyncio.sleep(300)  # 5 minutes
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{external_url}/api/history?symbol=BTC/USDT&interval=1h", timeout=15) as resp:
                    logger.info(f"💓 [KEEPALIVE] Self-ping status {resp.status}")
        except Exception as e:
            logger.warning(f"⚠️ [KEEPALIVE] Self-ping error: {e}")

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
                               open_position_count: int, step_tier_base: float = 800.0) -> tuple:
    """
    2-Slot Drawdown-Safe + +30% Step-Up Capital Allocation:
    - Fixed 2 concurrent slots (MAX_POSITION_COUNT = 2)
    - Base target: $400/slot ($800 / 2)
    - Once equity >= +30% ($1,040+), steps up target slot to 50% of new equity tier ($520+/slot)
    - Drawdown-Safe: if equity < tier, splits available free cash across remaining free slots
      so both slots ALWAYS execute without insufficient funds.
    """
    max_positions = MAX_POSITION_COUNT  # 2 slots
    if open_position_count >= max_positions:
        return max_positions, 0.0

    remaining_slots = max(1, max_positions - open_position_count)
    target_slot_usd = max(BASE_BALANCE, step_tier_base) / max_positions
    trade_usd = min(target_slot_usd, free / remaining_slots)
    trade_usd = min(trade_usd, MAX_ORDER_USD)
    return max_positions, round(trade_usd, 2)

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
    if state.get("trades_today", 0) >= MAX_TRADES_PER_DAY: return False, "trade_limit_day"
    
    # [STRICT] Max 3 trades per coin per day
    coin_trades = state.get(f"trades_{symbol}_today", 0)
    if coin_trades >= 3: return False, "trade_limit_coin"

    # Max Parallel Trades
    # [DYNAMIC] Calculate position limits based on current capital (passed in)
    open_trades = await db.get_open_trades()
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

# ------------------------
# HELPERS
# ------------------------

async def register_trade_open(symbol, strategy):
    state = await get_app_state()
    
    # Increment daily counters
    state = await db.get_state()
    today_trades = state.get("trades_today", 0) + 1
    state["trades_today"] = today_trades
    
    # Coin specific counter
    coin_key = f"trades_{symbol}_today"
    coin_trades = state.get(coin_key, 0) + 1
    state[coin_key] = coin_trades
    
    await db.set_state_key("trades_today", today_trades)
    await db.set_state_key(coin_key, coin_trades)

    # Update Timestamp map
    ts_map = state.get("last_trade_ts_map", {})
    ts_map[f"{strategy}:{symbol}"] = datetime.now().timestamp()
    await db.set_state_key("last_trade_ts_map", ts_map)

async def register_pnl_to_global(pnl):
    """Update total and daily realized PnL in the global state immediately."""
    state = await get_app_state()
    
    daily = safe(state.get("daily_realized_pnl", 0.0) + pnl)
    await db.set_state_key("daily_realized_pnl", daily)
    
    total = safe(state.get("total_realized_pnl", 0.0) + pnl)
    await db.set_state_key("total_realized_pnl", total)

async def register_trade_close(pnl_unused, symbol):
    """Side effects of a full trade closure (cooldowns, etc.)"""
    state = await get_app_state()
    
    # [QUANT] Set 1-Hour Cooldown
    cooldowns = state.get("exit_cooldowns", {})
    # Expire in 1 hour
    cooldowns[symbol] = datetime.now().timestamp() + (1 * 3600)
    await db.set_state_key("exit_cooldowns", cooldowns)

    # Note: PnL is now handled in real-time by register_pnl_to_global in execute_sell

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

    # 4. [REVERSE SYNC] Import Missing Trades (Exchange -> DB)
    # If we have a balance on Exchange but NO trade in DB, import it.
    try:
        # Re-fetch balance to be safe (or reuse if confident)
        # We iterate through the 'total' balance we already fetched
        for coin, qty in total.items():
            if coin == 'USDT': continue
            if qty <= 0: continue
            
            # Construct Symbol (Assumption: USDT pair)
            symbol = f"{coin}/USDT"
            
            # Check if this symbol exists in our Open DB Trades
            found = False
            for t in db_trades:
                if t['symbol'] == symbol:
                    found = True
                    break
            
            # [HARDENING] Double Check DB before Import (Anti-Race Condition)
            if not found:
                # Query DB directly to be absolutely sure it wasn't just opened
                # by the Strategy Manager in the last few milliseconds
                check_scan = await db.get_open_trades() # Refresh
                for scan_t in check_scan:
                    if scan_t['symbol'] == symbol:
                        found = True
                        break

            if not found:
                 # Check if the value is significant (> $5)
                 # We need current price
                 ticker = await safe_fetch_ticker(symbol)
                 if not ticker: continue
                 price = num(ticker['last'])
                 
                 value_usd = qty * price
                 if value_usd > 5.0:
                     logger.warning(f"📥 [SYNC] Found Orphaned Position on Exchange: {symbol} (Qty: {qty}). Importing...")
                     
                     # Create Trade Entry
                     # We don't know original entry, so we use current price as reference
                     # or maybe 0. It's better to use current price so PnL starts at 0?
                     # Actually, PnL will be wrong initially, but better than not tracking it.
                     
                     new_trade = {
                        "id": str(uuid.uuid4()),
                        "time": datetime.now(timezone.utc).isoformat(),
                        "symbol": symbol,
                        "side": "buy",
                        "strategy": "Manual_Import", # distinct tag
                        "entry_price": price, # Approximate
                        "qty": qty,
                        "used_usd": value_usd,
                        "status": "open",
                        "pnl": 0.0,
                        "sl": 0.0,
                        "tp": 0.0,
                        "exit_price": 0.0,
                        "current_price": price,
                        "unrealized_pnl": 0.0,
                        "fees_usd": 0.0,
                        "highest_price": price,
                        "trail_active": False,
                        "trail_sl": 0.0
                     }
                     await db.add_trade(new_trade)
                     logger.info(f"✅ [IMPORT] Successfully imported {symbol}")

    except Exception as e:
        logger.error(f"[REVERSE SYNC] Error: {e}")

# ------------------------------------------------------------------------------

# EXECUTION & ORDER MANAGEMENT
# ------------------------------------------------------------------------------
async def execute_buy(symbol, sl_pct, tp_pct, strategy, sl_absolute=None, tp_absolute=None):
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
    
    # [2-SLOT DYNAMIC SIZING: $400 Base, Drawdown-Safe < $800, +30% Step-Up >= $1,040]
    equity, locked, free, _, _ = await get_equity_locked_free()
    open_trades = await db.get_open_trades()
    state = await get_app_state()

    step_tier_base = float(state.get("step_tier_base", BASE_BALANCE))
    while equity >= step_tier_base * 1.30:
        step_tier_base = round(equity, 2)
        await db.set_state_key("step_tier_base", step_tier_base)
        await db.set_state_key("trade_usd", round(step_tier_base / MAX_POSITION_COUNT, 2))
        logger.info(f"🚀 [+30% STEP-UP UNLOCKED] Equity reached ${equity:.2f} -> New Slot Size: ${step_tier_base / MAX_POSITION_COUNT:.2f}")

    _, usd = calculate_position_limits(equity, locked, free, len(open_trades), step_tier_base=step_tier_base)
    logger.info(
        f"⚖️ [2-SLOT SIZING] {symbol} | Equity: ${equity:.2f} | Free: ${free:.2f} | "
        f"Open Slots: {len(open_trades)}/{MAX_POSITION_COUNT} | Slot Size: ${usd:.2f}"
    )

    if usd < 5: 
        logger.info(f"[BUY SKIP] {symbol}: Size ${usd:.2f} too small")
        return # Too small
    
    if not await symbol_exposure_ok(symbol, usd): return
    ok, reason = await can_place_trade(symbol, usd, strategy, equity, locked, free)
    if not ok:
        logger.info(f"[BUY SKIP] {symbol}: {reason}")
        return

    # [RULE] Use Strategy TP (1:2.5+ RR) if provided, else fallback to 1:2.5 RR
    if tp_absolute is not None and tp_absolute > price:
        tp = num(tp_absolute)
        logger.info(f"🎯 [TP CALC] Strategy Asymmetric RR -> Profit Target @ {tp}")
    elif sl_dist_usd > 0:
        tp_price = price + (2.5 * sl_dist_usd)
        tp = num(tp_price)
        logger.info(f"🎯 [TP CALC] 1:2.5 RR -> Profit Target @ {tp}")
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
        fees = safe(usd * COMMISSION_PCT)
        qty = safe((usd / price) * (1 - COMMISSION_PCT)) # Fee deducted from asset
        used = usd # Porton of USDT wallet spent
        # Note: sl and tp are already calculated from sl_absolute or sl_pct above
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

        pnl = safe((exec_price * sell_qty) - (trade['used_usd'] * (sell_qty / trade['qty'])) - fees)
        await register_pnl_to_global(pnl) # [FIX] Real-time Net Earnings update
        
        remaining = safe(trade['qty'] - sell_qty)
        
        # Clean Dust
        if remaining * price < 2.0 or pct >= 99.0:
            total_trade_pnl = safe(trade['pnl'] + pnl)
            await db.update_trade(trade_id, {
                "status": "closed",
                "qty": 0,
                # "used_usd": 0, # [FIX] Preserve used_usd for history/stats
                "exit_price": exec_price,
                "pnl": total_trade_pnl,
                "fees_usd": safe(trade['fees_usd'] + fees),
                "exit_time": datetime.now(timezone.utc).isoformat()
            })
            await register_trade_close(0.0, trade['symbol'])
            logger.info(f"💰 [TRADE CLOSED] {trade['symbol']} | PnL: {pnl:.4f} | Reason: {reason}")
            try:
                await AgentGate.reflect_on_closed_trade(trade, exec_price, total_trade_pnl, reason, db)
            except Exception as ref_err:
                logger.warning(f"[REFLECTOR WARN] {ref_err}")
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
            if TRADE_MODE == "live":
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
                    
                    unreal = (price * t['qty']) - t['used_usd']
                    highest = max(t['highest_price'], price)
                    
                    updates = {
                        "current_price": price,
                        "unrealized_pnl": safe(unreal),
                        "highest_price": highest
                    }
                    
                    # -----------------------------------------------
                    # STRATEGY 2 TRAILING SL (Activate @ 0.438 [+2R], Lock +1.6R, Trail 0.5R)
                    # -----------------------------------------------
                    t_sl = float(t.get('sl') or 0.0)
                    t_tp = float(t.get('tp') or 0.0)
                    entry_p = float(t.get('entry_price') or price)

                    # 1. STOP LOSS / TRAILING STOP EXIT (Immediate Live Touch)
                    if t_sl > 0 and price <= t_sl:
                        if t.get("trail_active") or t_sl > entry_p:
                            logger.info(f"🏆 [TRAIL SL PROFIT HIT] {symbol} @ {price:.6g} <= Trail SL {t_sl:.6g}")
                            await execute_sell(t['id'], 100, "trail_tp")
                        else:
                            logger.info(f"🛑 [SL HIT] {symbol} @ {price:.6g} <= SL {t_sl:.6g}")
                            await execute_sell(t['id'], 100, "stop_loss")
                        continue

                    # 2. TRAILING SL ACTIVATION & RATCHET AT 0.438 (+2.0R)
                    # Since 0.438 - 0.146 = 0.292 = 2 * 0.146, (t_tp - entry_p) / 2.0 is always exact 1R
                    one_r = (t_tp - entry_p) / 2.0 if t_tp > entry_p else abs(entry_p - t_sl)
                    if t_tp > 0 and one_r > 0 and highest >= t_tp:
                        locked_floor = entry_p + (1.6 * one_r)  # Lock +1.6R immediately at 0.438
                        trail_level = highest - (0.5 * one_r)   # Trail 0.5R behind highest_price
                        new_sl = round(max(t_sl, locked_floor, trail_level), 8)
                        updates["trail_active"] = True
                        updates["trail_sl"] = new_sl
                        if new_sl > t_sl:
                            updates["sl"] = new_sl
                            logger.info(
                                f"📈 [TRAIL SL RATCHET] {symbol} | High {highest:.6g} >= 0.438 ({t_tp:.6g}) | "
                                f"SL locked/trailed: {t_sl:.6g} -> {new_sl:.6g}"
                            )

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

async def scan_smc_target(symbol, ex, active_strategies, context=None):
    """
    Returns: (symbol, scanner_items, diagnostic, should_buy, bullish_trend_found)
    Scans 1H Big-Move Launchpad Fibonacci (0 / 0.146 / 0.438 / 1) with live price touch entry.
    """
    async with scan_sem:
        try:
            if not context or not context.get("ohlcv_1h"):
                ohlcv_1h = await ex.fetch_ohlcv(symbol, '1h', limit=120)
                if not ohlcv_1h or len(ohlcv_1h) < 50:
                    return (symbol, None, None, False, False)
                context = {
                    "ohlcv_1h": ohlcv_1h,
                    "symbol_pct_change": float((context or {}).get("symbol_pct_change", 0.0))
                }
            else:
                ohlcv_1h = context["ohlcv_1h"]
                if not ohlcv_1h or len(ohlcv_1h) < 50:
                    return (symbol, None, None, False, False)

            # Check Signal with 1H Big-Move Launchpad Fibonacci Touch Logic
            is_valid_signal, diagnostic = StrategyManager.check_signal(symbol, ohlcv_1h, context)

            # [TRADINGAGENTS GATE] Pre-Buy Bull vs. Bear Debate & Risk Judge
            if is_valid_signal and diagnostic:
                approved, debate = await AgentGate.evaluate_signal(
                    symbol, diagnostic, ohlcv_1h, context, db
                )
                diagnostic['bull_score'] = debate['bull_score']
                diagnostic['bear_score'] = debate['bear_score']
                diagnostic['agent_verdict'] = debate['verdict']
                if not approved:
                    is_valid_signal = False
                    diagnostic['reason'] = debate['verdict']
                    logger.info(f"⚖️ [AGENT GATE VETO] {symbol}: {debate['verdict']}")
                else:
                    diagnostic['reason'] = f"{diagnostic.get('reason', '')} | {debate['verdict']}"
                    logger.info(f"✅ [AGENT GATE PASS] {symbol}: {debate['verdict']}")

            if diagnostic:
                diagnostic['trend_1h'] = "Bullish"

            # Get Scanner Data (Visuals for 1H Big-Move Fibonacci)
            scanner_data = StrategyManager.get_scanner_data(symbol, ohlcv_1h, context)

            if scanner_data:
                df_entry = pd.DataFrame(ohlcv_1h, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                v_ok, v_msg = check_volatility_ok(df_entry, '1h')

                for item in scanner_data:
                    item['trend'] = "Bullish"
                    item['vol_ok'] = v_ok
                    item['vol_msg'] = v_msg

            return (symbol, scanner_data, diagnostic, is_valid_signal, True)

        except Exception as e:
            logger.error(f"Error scanning {symbol}: {e}")
            return (symbol, None, None, False, False)


async def strategy_loop():
    logger.info("Strategy Loop Started (Parallelized V2)...")
    ignored = ["USDC", "USDP", "FDUSD", "TUSD", "EUR", "GBP", "DAI", 
               "SAPIEN", "DATA", "FTT", "BTTC", "GUN"] 
    global smc_scanner_cache
    global market_trend_score, market_trend_label
    global last_loop_ts, last_loop_error, last_top_gainers
    
    while True:
        try:
            start_ts = datetime.now()
            last_loop_ts = start_ts.isoformat()
            logger.info(f"[DEBUG] Loop Cycle Start {start_ts}")
            # [SAFETY] Periodic Sync
            await sync_portfolio_with_exchange()
            
            # [RESET] Check for new day immediately
            await daily_reset_if_needed()
            
            # [SAFETY] Global Protection Check (-4R Daily, -8R Strategy)
            all_trades_today = await db.get_all_trades_desc(limit=50) # Approx
            r_total_today = 0.0
            r_total_strategy = 0.0 # Could calculate from all, but focus on recent or paper performance
            
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            for t_old in all_trades_today:
                 if t_old['status'] == 'closed':
                      dist_old = abs(t_old['entry_price'] - t_old['sl']) if t_old['sl'] > 0 else 0
                      # Reconstruct initial risk: (dist / entry) * used_usd
                      init_risk = (dist_old / t_old['entry_price']) * t_old['used_usd'] if t_old['entry_price'] > 0 else 0
                      r_val = t_old['pnl'] / init_risk if init_risk > 0 else 0
                      
                      if today_str in t_old['time']:
                           r_total_today += r_val
                      r_total_strategy += r_val

            if TRADE_MODE == "live" and r_total_today <= DAILY_LOSS_LIMIT_R:
                 logger.warning(f"🔋 [CIRCUIT BREAKER] Daily R-Total {r_total_today:.1f} <= {DAILY_LOSS_LIMIT_R}. Trading paused for today.")
                 await asyncio.sleep(3600)
                 continue
            
            if r_total_strategy <= STRATEGY_DEATH_LIMIT_R:
                 logger.critical(f"💀 [STRATEGY DEATH] Total drawdown {r_total_strategy:.1f}R hits limit. Disabling Bot.")
                 await db.set_state_key("auto_trading", False)
                 await asyncio.sleep(3600)
                 continue

            state = await get_app_state()
            if not state.get("auto_trading") or state.get("kill_switch"):
                await asyncio.sleep(5)
                continue
                
            # [SAFETY] Daily Loss Count Limit - REMOVED
            
            # [OPTIMIZATION] Time Filter: Avoid Late NY (Death Zone)
            # 17:00 - 20:00 UTC (User stats show -33% WR / Negative PnL here)
            # [UPDATE] Disabled upon user request. Strict logic handles quality now.
            # now_utc = datetime.now(timezone.utc)
            # if 17 <= now_utc.hour < 20:
            #      logger.warning(f"💤 [TIME FILTER] Late NY Session ({now_utc.strftime('%H:%M')} UTC). Sleeping until 20:00 UTC.")
            #      smc_scanner_cache = []
            #      await asyncio.sleep(60)
            #      continue
            
            # [SCAN] 2. BTC Regime Gate & Universe
            # A. Fetch BTC 1H for Regime
            try:
                # [BTC GATE] Optimized History Fetch (400 candles for best trend alignment)
                # This window (400h) yields a Bullish cross matching user visuals
                btc_ohlcv_1h = await ex_live.fetch_ohlcv("BTC/USDT", "1h", limit=400)

                if not btc_ohlcv_1h or len(btc_ohlcv_1h) < 200:
                    logger.warning(f"BTC Gate: Insufficient 1H data ({len(btc_ohlcv_1h)}/200). Skipping.")
                    await asyncio.sleep(60)
                    continue
                
                # Analyze BTC
                btc_ana = StrategyManager.get_btc_analysis(btc_ohlcv_1h)
                
                # [DEBUG TIMESTAMP]
                first_t = pd.to_datetime(btc_ohlcv_1h[0][0], unit='ms')
                last_t = pd.to_datetime(btc_ohlcv_1h[-1][0], unit='ms')
                logger.debug(f"[BTC DATA] Count: {len(btc_ohlcv_1h)}, Start: {first_t}, End: {last_t}")

                # Gate Logic for Top Gainers:
                # Top Gainers have independent momentum; only block if BTC is in extreme crash (1H RSI < 30)
                if btc_ana.get('rsi', 50) < 30:
                     market_trend_score = 0
                     market_trend_label = "Extreme Crash (Gate Closed)"
                     logger.info(f"🚫 [BTC CRASH BLOCK] {btc_ana['reason']}")
                     await asyncio.sleep(60)
                     continue
                
                market_trend_score = 100 if (btc_ana['close_gt_ema200'] and btc_ana['ema50_gt_ema200']) else 65
                market_trend_label = "Bullish (Top Gainers Active)" if market_trend_score == 100 else "Neutral (Top Gainers Active)"
                btc_pct = btc_ana['pct_change']

            except Exception as e:
                logger.error(f"BTC Gate Error: {e}")
                btc_pct = 0.0
                await asyncio.sleep(60)
                continue

            # Fetch Tickers for context
            try:
                tickers = await ex_live.fetch_tickers()
                async with err_lock:
                    global consecutive_api_errors
                    consecutive_api_errors = 0 # Reset on success
                btc_ticker = tickers.get("BTC/USDT", {})
                btc_pct = float(btc_ticker.get('percentage', 0))
                
                # [TOP GAINERS FILTER FOR FIBONACCI BIG MOVES]
                # Filter for LIVE ACTIVE Spot Top Gainers (excludes delisted/halted "BREAK" coins like HFT/USDT)
                now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                valid_tickers = []
                for sym, t in tickers.items():
                    stablecoins = ['USDC', 'TUSD', 'FDUSD', 'USD1', 'EUR', 'XUSD', 'RLUSD', 'USDE', 'BUSD', 'PAXG']
                    is_stablecoin = any(s in sym for s in stablecoins)
                    if sym.endswith('/USDT') and 'UP/' not in sym and 'DOWN/' not in sym and not is_stablecoin:
                        try:
                            mkt = ex_live.markets.get(sym)
                            if not mkt or not mkt.get('active') or not mkt.get('spot'):
                                continue
                            if mkt.get('info', {}).get('status', 'TRADING') != 'TRADING':
                                continue
                            t_ts = int(t.get('timestamp') or 0)
                            if t_ts > 0 and (now_ms - t_ts) > 600_000:  # Must have traded in the last 10 minutes
                                continue
                            pct = float(t.get('percentage', 0))
                            vol = float(t.get('quoteVolume', 0))
                            if vol >= 2000000 and pct > 0.0:
                                valid_tickers.append((sym, vol, pct))
                        except:
                            pass
                
                # Sort by highest 24h percentage gain (Top Gainers) so we catch big impulsive moves
                valid_tickers.sort(key=lambda x: x[2], reverse=True)
                top_gainers = [x[0] for x in valid_tickers[:20]]
                if not top_gainers:
                    top_gainers = ALLOWED_SYMBOLS
                
                last_top_gainers = top_gainers
            except Exception as e:
                logger.warning(f"Ticker filter error: {e}")
                btc_pct = 0.0
                top_gainers = ALLOWED_SYMBOLS # Fallback
                last_top_gainers = top_gainers
            
            open_trades = await db.get_open_trades()
            active_strats = ["EMA_Pullback"]
            
            # ---------------------------------------------------------
            # MARKET INTELLIGENCE (BTC Directional Gate Active)
            # ---------------------------------------------------------
            market_trend_label = "Bullish"
            market_trend_score = 100
            btc_regime = "bullish"
            
            # Context Object for passing BTC data
            scan_context = {"btc_pct": btc_pct}

            # We fetch all candidates in parallel with a Semaphore
            smc_tasks = []
            
            async def scan_with_data_fetch(s):
                 """Parallel wrapper to fetch data and then scan."""
                 async with scanner_semaphore:
                     try:
                        ctx = {
                            "btc_pct": btc_pct,
                            "ohlcv_1h": await ex_live.fetch_ohlcv(s, "1h", limit=200),
                            "symbol_pct_change": float(tickers.get(s, {}).get('percentage', 0))
                        }
                        # Reset error counter on successful OHLCV fetch
                        async with err_lock:
                            global consecutive_api_errors
                            consecutive_api_errors = 0
                            
                        return await scan_smc_target(s, ex_live, active_strats, context=ctx)
                     except Exception as e:
                        logger.error(f"Failed parallel scan for {s}: {e}")
                        return (s, None, None, False, False)

            for s in top_gainers:
                 smc_tasks.append(scan_with_data_fetch(s))

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
                    diag['symbol'] = sym
                    diag['time'] = datetime.now(timezone.utc).isoformat()
                    near_hits.insert(0, diag)
                
                if sig:
                    # Execute Trade (Sequential, Safe)
                    sl_abs = diag.get('sl')
                    tp_abs = diag.get('tp')
                    trigger_type = diag.get('trigger', 'SMC')
                    strategy_name = f"SMC_{trigger_type}"
                    
                    await execute_buy(sym, None, None, strategy_name, sl_absolute=sl_abs, tp_absolute=tp_abs)
                
                # [VISIBILITY] Log Rejections (User Assurance)
                elif diag and "reason" in diag:
                     # Only log interesting rejections (not just "Trend Down" which is common? 
                     # No, log all for now to prove it works).
                     logger.info(f"🛡️ [FILTER BLOCK] {sym}: {diag['reason']}")
                
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
            
            logger.info(f"📈 [MARKET TREND] Score: {market_trend_score}/100 ({market_trend_label}) | Regime: {btc_regime}")

            # ---------------------------------------------------------
            # END OF LOOP
            # ---------------------------------------------------------
            duration = (datetime.now() - start_ts).total_seconds()
            logger.info(f"[SCANNER] Cycle complete in {duration:.2f}s.")
            
        except Exception as e:
            last_loop_error = str(e)
            logger.exception("Strategy loop crashed")
        
        await asyncio.sleep(STRATEGY_INTERVAL)


# ------------------------------------------------------------------------------
# FASTAPI ENDPOINTS
# ------------------------------------------------------------------------------
@app.get("/stats", dependencies=[Depends(get_current_user)])
async def stats():
    equity, locked, free, api_status, api_error = await get_equity_locked_free()
    state = await get_app_state()
    
    all_trades = await db.get_all_trades_desc(limit=500)
    closed = [t for t in all_trades if t['status'] == 'closed']
    wins = [t for t in closed if t['pnl'] > 0]
    total_realized_pnl = state.get("total_realized_pnl", 0.0) # [FIX] Real-time from state
    
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

@app.get("/trades", dependencies=[Depends(get_current_user)])
async def get_trades():
    return await db.get_all_trades_desc()

@app.get("/positions", dependencies=[Depends(get_current_user)])
async def get_positions():
    # [OPTIMIZATION] Read from DB directly. Background worker handles sync.
    return await db.get_open_trades()

@app.get("/signals", dependencies=[Depends(get_current_user)])
async def get_signals():
    return near_hits

@app.get("/agent-debates", dependencies=[Depends(get_current_user)])
async def get_agent_debates(limit: int = 30):
    return await db.get_recent_debates(limit=limit)

@app.get("/reflections", dependencies=[Depends(get_current_user)])
async def get_reflections(limit: int = 30):
    return await db.get_recent_reflections(limit=limit)

@app.get("/history")
async def get_history(symbol: str, interval: str = "1h"):
    """Fetch primitive OHLCV history and Big-Move Launchpad Fibonacci (0, 0.146, 0.438, 1) levels for custom charts"""
    try:
        limit = 200
        ohlcv = await ex_live.fetch_ohlcv(symbol, interval, limit=limit)
             
        if not ohlcv:
            return {"candles": [], "fib": None}
        df_hist = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume'])

        candles = []
        for _, row in df_hist.iterrows():
            t_sec = int(row['time'] / 1000)
            candles.append({
                "time": t_sec, 
                "open": float(row['open']),
                "high": float(row['high']),
                "low": float(row['low']),
                "close": float(row['close'])
            })

        min_imp = 6.0 if interval in ("1h", "4h") else 4.0
        fib = StrategyManager.compute_fib_levels(df_hist, lookback_window=40, min_impulse_pct=min_imp)

        return {
            "candles": candles,
            "fib": fib
        }
    except Exception as e:
        logger.error(f"History fetch error: {e}")
        return {"candles": [], "fib": None}

@app.get("/smc-scanner", dependencies=[Depends(get_current_user)])
async def get_smc_scanner():
    return smc_scanner_cache

@app.post("/paper-sell", dependencies=[Depends(get_current_admin)])
async def paper_sell(trade_id: str = Query(...), sell_pct: float = Query(100.0)):
    await execute_sell(trade_id, sell_pct, reason="manual_web")
    return {"status": "ok"}

@app.post("/update-sl-tp", dependencies=[Depends(get_current_admin)])
async def update_sl_tp(trade_id: str = Query(...), sl: float = Query(...), tp: float = Query(...)):
    await db.update_trade(trade_id, {"sl": sl, "tp": tp})
    return {"status": "ok"}

@app.post("/admin/kill", dependencies=[Depends(get_current_admin)])
async def kill():
    await db.set_state_key("kill_switch", True)
    await db.set_state_key("auto_trading", False)
    return {"status": "killed"}

@app.post("/admin/resume", dependencies=[Depends(get_current_admin)])
async def resume():
    await db.set_state_key("kill_switch", False)
    await db.set_state_key("auto_trading", True)
    return {"status": "resumed"}

@app.get("/admin/trade-usd", dependencies=[Depends(get_current_admin)])
async def get_trade_usd():
    state = await get_app_state()
    return {"trade_usd": state.get("trade_usd", 10.0)}

@app.post("/admin/set-trade-usd", dependencies=[Depends(get_current_admin)])
async def set_trade_usd(amount: float = Query(..., gt=0)):
    logger.info(f"[ADMIN] Updating trade_usd to ${amount}")
    await db.set_state_key("trade_usd", float(amount))
    return {"status": "ok"}

# Serve compiled Next.js static dashboard at "/" in cloud deployments (Render Free single-service mode)
from fastapi.staticfiles import StaticFiles
_static_out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crypto-dashboard", "out")
if os.path.isdir(_static_out):
    app.mount("/", StaticFiles(directory=_static_out, html=True), name="dashboard")
