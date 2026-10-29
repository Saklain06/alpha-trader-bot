import pandas as pd
import numpy as np


def calculate_ema(series, span):
    if series.empty: return series
    series = series.ffill().fillna(0)
    return series.ewm(span=span, adjust=False).mean()

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss.replace(0, 0.0001))
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(period).mean()

def calculate_vwap(df):
    v = df['vol']
    tp = (df['high'] + df['low'] + df['close']) / 3
    return (tp * v).cumsum() / v.cumsum()

def calculate_bollinger_bands(series, period=20, std_dev=2):
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)
    return sma, upper_band, lower_band

class StrategyManager:
    # Tracks (symbol, swing_low_ts, swing_high_ts) so we only trade the FIRST pullback to 0.146 per impulse leg
    consumed_fib_swings = set()

    @staticmethod
    def get_btc_analysis(ohlcv):
        """
        Analyze BTC 1H for Global Filter using deep history (2000 candles).
        1. BTC 1H Close > SMA 200
        2. BTC 1H EMA 50 > SMA 200
        3. BTC 1H RSI (14) > 50
        """
        if not ohlcv or len(ohlcv) < 200:
            return {
                "close_gt_ema200": False, 
                "ema50_gt_ema200": False, 
                "rsi_gt_50": False, 
                "reason": f"Insufficient Data ({len(ohlcv) if ohlcv else 0}/200)",
                "close": 0, "ema50": 0, "ema200": 0, "rsi": 0
            }

        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        df['close'] = df['close'].astype(float)
        
        # Calculate Indicators
        df['ema50'] = calculate_ema(df['close'], 50)
        df['sma200'] = df['close'].rolling(window=200).mean() # SMA is robust for macro trend
        df['rsi'] = calculate_rsi(df['close'], 14)
        
        last = df.iloc[-1]
        
        # REAL MACRO GATE: BTC must be in a confirmed 1H uptrend
        close_gt_sma200 = float(last['close']) > float(last['sma200'])
        ema50_gt_sma200 = float(last['ema50']) > float(last['sma200'])
        rsi_bullish = float(last['rsi']) >= 48.0
        
        reasons = []
        if not close_gt_sma200:
            reasons.append(f"BTC Price ({last['close']:.0f}) <= SMA200 ({last['sma200']:.0f})")
        if not ema50_gt_sma200:
            reasons.append(f"BTC EMA50 ({last['ema50']:.0f}) <= SMA200 ({last['sma200']:.0f})")
        if not rsi_bullish:
            reasons.append(f"BTC RSI ({last['rsi']:.1f}) < 48")
        
        is_gate_open = close_gt_sma200 and ema50_gt_sma200 and rsi_bullish
        btc_pct = (float(last['close']) - float(last['open'])) / float(last['open']) * 100
        
        return {
            "close_gt_ema200": close_gt_sma200, # Keep keys compatible with main.py
            "ema50_gt_ema200": ema50_gt_sma200, 
            "rsi_gt_50": rsi_bullish,
            "gate_open": is_gate_open,
            "reason": " & ".join(reasons) if reasons else "Bullish Uptrend Confirmed",
            "pct_change": float(btc_pct),
            "close": float(last['close']),
            "ema50": float(last['ema50']),
            "ema200": float(last['sma200']),
            "rsi": float(last['rsi'])
        }

    @staticmethod
    def get_analysis(symbol, ohlcv, context=None):
        """
        Analyze the chart for the 'Disciplined Pullback' setup (15m Timeframe).
        """
        if not ohlcv or len(ohlcv) < 60:
            return None

        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # 1. Indicators
        df['ema20'] = calculate_ema(df['close'], 20)
        df['ema50'] = calculate_ema(df['close'], 50)
        df['rsi'] = calculate_rsi(df['close'], 14)
        df['avg_vol'] = df['vol'].rolling(window=20).mean()
        
        return {
            "df": df,
            "qualified": True # Qualification checks moved to check_signal for granularity
        }

    @staticmethod
    def _find_big_move_anchors(highs, lows, closes, win_start: int, win_end: int, max_impulse_bars: int = 15):
        """
        Big-Move Launchpad Anchor:
          1. Finds the highest breakout peak (Fib 1) in the window.
          2. Looks back up to `max_impulse_bars` before the peak for the lowest point.
          3. Walks forward across flat base candles to anchor Fib 0 at the exact launchpad candle
             where the explosive move began.
        """
        peak_start = min(win_start + 4, max(1, win_end - 2))
        if peak_start >= win_end:
            return None

        high_idx = peak_start + int(np.argmax(highs[peak_start:win_end]))
        swing_high = float(highs[high_idx])
        if high_idx <= 0:
            return None

        imp_start = max(0, high_idx - max_impulse_bars)
        raw_low_idx = imp_start + int(np.argmin(lows[imp_start:high_idx]))
        raw_low = float(lows[raw_low_idx])
        raw_rng = swing_high - raw_low
        if raw_low <= 0 or raw_rng <= 0:
            return None

        low_idx = raw_low_idx
        base_low_ceil = raw_low + 0.08 * raw_rng
        base_close_ceil = raw_low + 0.20 * raw_rng
        for k in range(raw_low_idx + 1, high_idx):
            if float(lows[k]) <= base_low_ceil and float(closes[k]) <= base_close_ceil:
                low_idx = k
            else:
                break

        swing_low = float(lows[low_idx])
        return low_idx, swing_low, high_idx, swing_high

    @staticmethod
    def check_signal(symbol, ohlcv, context=None):
        """
        1H Big-Move Launchpad Fibonacci (0 / 0.146 / 0.438 / 1) Touch-Entry + Trailing SL Strategy:
          - 0     = Launchpad Base Low of a >= 6.0% 1H impulsive breakout
          - 1     = Breakout Peak High of that move
          - 0.146 = Instant Touch Entry on pullback: Low + 0.146 * (High - Low)
          - SL    = Initial SL at 0 (Launchpad Low)
          - 0.438 = +2.0R Trailing SL Activation Level: once touched, locks +1.6R (0.380 Fib)
                    and trails 0.5R behind highest_price uncapped.
          - Does NOT wait for candle close: checks live forming candle (df.iloc[-1]).
        """
        analysis = StrategyManager.get_analysis(symbol, ohlcv, context)
        if not analysis:
            return False, {}

        df = analysis["df"]
        n = len(df)
        lookback_window = 40
        max_impulse_bars = 15
        min_impulse_pct = 6.0  # Minimum 6.0% 1H big-move impulse

        if n < lookback_window + 3:
            return False, {"reason": "Insufficient 1H history for Big-Move Fibonacci"}

        highs = df["high"].astype(float).values
        lows = df["low"].astype(float).values
        closes = df["close"].astype(float).values
        timestamps = df["ts"].values

        # Current live forming candle index is n - 1
        i = n - 1
        win_start = max(0, i - lookback_window)
        win_end = i  # up to previous completed candle (i - 1)

        anchors = StrategyManager._find_big_move_anchors(
            highs, lows, closes, win_start, win_end, max_impulse_bars=max_impulse_bars
        )
        if not anchors:
            return False, {"reason": "No valid Big-Move Launchpad anchor found"}

        low_idx, swing_low, high_idx, swing_high = anchors

        if high_idx >= i - 1:
            return False, {"reason": f"Impulse High at {swing_high:.4g} just formed; waiting for pullback"}

        impulse_range = swing_high - swing_low
        if swing_low <= 0 or impulse_range <= 0:
            return False, {"reason": "Invalid Fibonacci range"}

        impulse_pct = (impulse_range / swing_low) * 100.0
        if impulse_pct < min_impulse_pct:
            return False, {
                "reason": f"Impulse move ({impulse_pct:.2f}%) < {min_impulse_pct:.1f}% min threshold"
            }

        # Compute exact Fibonacci levels
        fib_0 = swing_low
        fib_0146 = swing_low + 0.146 * impulse_range
        fib_0438 = swing_low + 0.438 * impulse_range
        fib_1 = swing_high

        swing_key = (symbol, int(timestamps[low_idx]), int(timestamps[high_idx]))
        if swing_key in StrategyManager.consumed_fib_swings:
            return False, {"reason": "Fib 0.146 level already tested on this impulse leg"}

        # Strict Invalidation Checks after Peak (high_idx):
        # a) Price NEVER dropped at or below Fib 0 (SL) after the Peak
        if float(np.min(lows[high_idx + 1 : i + 1])) <= fib_0:
            StrategyManager.consumed_fib_swings.add(swing_key)
            return False, {"reason": f"Invalidated: Price already passed 0 SL ({fib_0:.4g}) after Peak"}

        # b) Between high_idx + 1 and previous candle i - 1, price didn't break Fib 1 or already touch Fib 0.146
        if high_idx + 1 < i:
            if float(np.max(highs[high_idx + 1 : i])) > fib_1:
                return False, {"reason": "Peak High broken; re-anchoring Fibonacci"}
            if float(np.min(lows[high_idx + 1 : i])) <= fib_0146:
                StrategyManager.consumed_fib_swings.add(swing_key)
                return False, {"reason": "Previous candle already consumed Fib 0.146 pullback"}

        # Live Touch Check (no waiting for 1H candle close!)
        live_price = float(closes[i])
        live_low = float(lows[i])
        prev_close = float(closes[i - 1])

        if prev_close <= fib_0146:
            StrategyManager.consumed_fib_swings.add(swing_key)
            return False, {"reason": "Invalidated: Price already below 0.146 before current candle"}

        dist_to_0146_pct = ((live_price - fib_0146) / fib_0146) * 100.0 if fib_0146 > 0 else 99.0

        # Trigger instant entry when live price pulls back down to <= 0.146 (with 0.25% touch tolerance) and stays > Fib 0 (SL)
        if live_low <= (fib_0146 * 1.0025) and live_price > (fib_0 * 1.001) and live_price <= (fib_0146 * 1.005):
            StrategyManager.consumed_fib_swings.add(swing_key)
            return True, {
                "signal": "long",
                "entry_price": round(live_price, 8),
                "sl": round(fib_0, 8),
                "tp": round(fib_0438, 8),
                "fib_0": round(fib_0, 8),
                "fib_0146": round(fib_0146, 8),
                "fib_0438": round(fib_0438, 8),
                "fib_1": round(fib_1, 8),
                "impulse_pct": round(impulse_pct, 2),
                "trigger": "Fib_0146_BigMove_Trail",
                "reason": (
                    f"1H Big-Move 0.146 Touch Entry (Impulse +{impulse_pct:.1f}% | "
                    f"Entry {live_price:.4g} | SL(0) {fib_0:.4g} | Trail Trigger(0.438) {fib_0438:.4g})"
                ),
            }

        return False, {
            "reason": (
                f"Active 1H Big-Move (+{impulse_pct:.1f}%): Price {live_price:.4g} waiting for "
                f"0.146 touch @ {fib_0146:.4g} ({dist_to_0146_pct:+.2f}% away) | SL(0): {fib_0:.4g} | Trail@0.438: {fib_0438:.4g}"
            ),
            "fib_0": round(fib_0, 8),
            "fib_0146": round(fib_0146, 8),
            "fib_0438": round(fib_0438, 8),
            "fib_1": round(fib_1, 8),
            "impulse_pct": round(impulse_pct, 2),
        }

    @staticmethod
    def compute_fib_levels(df: pd.DataFrame, lookback_window: int = 40, min_impulse_pct: float = 6.0):
        """
        Computes the active Big-Move Launchpad Fibonacci (0, 0.146, 0.438, 1) levels on a DataFrame of candles.
        Marks the setup as invalid if price after the Peak (1) already passed 0 (SL)
        or already consumed the 0.146 pullback on a prior candle.
        """
        if df is None or len(df) < 15:
            return None

        n = len(df)
        lb = min(lookback_window, n - 2)
        i = n - 1
        win_start = max(0, i - lb)

        highs = df["high"].astype(float).values
        lows = df["low"].astype(float).values
        closes = df["close"].astype(float).values
        ts_col = "time" if "time" in df.columns else "ts"
        timestamps = df[ts_col].values

        anchors = StrategyManager._find_big_move_anchors(
            highs, lows, closes, win_start, n, max_impulse_bars=15
        )
        if not anchors:
            return None

        low_idx, swing_low, high_idx, swing_high = anchors

        impulse_range = swing_high - swing_low
        if swing_low <= 0 or impulse_range <= 0:
            return None

        impulse_pct = (impulse_range / swing_low) * 100.0
        fib_0 = swing_low
        fib_0146 = swing_low + 0.146 * impulse_range
        fib_0438 = swing_low + 0.438 * impulse_range
        fib_1 = swing_high

        # Check if price after Peak (1) already passed 0 (SL) or already consumed 0.146
        sl_passed = False
        already_consumed = False
        if high_idx + 1 < n:
            if float(np.min(lows[high_idx + 1 : n])) <= fib_0:
                sl_passed = True
            elif high_idx + 1 < i and float(np.min(lows[high_idx + 1 : i])) <= fib_0146:
                already_consumed = True

        # Check if candle data is stale (delisted / halted coin like HFT/USDT)
        last_ts = int(timestamps[-1])
        last_ts_sec = int(last_ts / 1000) if last_ts > 10_000_000_000 else last_ts
        import time as _time
        is_delisted_stale = (_time.time() - last_ts_sec) > (6 * 3600)

        is_valid = (not is_delisted_stale) and (not sl_passed) and (not already_consumed) and (impulse_pct >= min_impulse_pct)
        if is_delisted_stale:
            status = "DELISTED / HALTED ON BINANCE"
        elif sl_passed:
            status = "INVALIDATED (Price Passed 0 SL)"
        elif already_consumed:
            status = "CONSUMED (0.146 Already Tested)"
        elif impulse_pct < min_impulse_pct:
            status = f"WEAK IMPULSE (+{impulse_pct:.1f}% < {min_impulse_pct:.0f}%)"
        else:
            status = "ACTIVE BIG-MOVE SETUP"

        low_t = int(timestamps[low_idx])
        high_t = int(timestamps[high_idx])
        if low_t > 10_000_000_000:
            low_t = int(low_t / 1000)
        if high_t > 10_000_000_000:
            high_t = int(high_t / 1000)

        return {
            "valid": is_valid,
            "status": status,
            "sl_passed": sl_passed,
            "fib_0": round(fib_0, 8),
            "fib_0146": round(fib_0146, 8),
            "fib_0438": round(fib_0438, 8),
            "fib_1": round(fib_1, 8),
            "impulse_pct": round(impulse_pct, 2),
            "low_time": low_t,
            "high_time": high_t,
        }

    @staticmethod
    def get_scanner_data(symbol, ohlcv, context=None):
        """
        Return visuals: ONLY active, unbroken Big-Move Fibonacci (0, 0.146, 0.438, 1) setups for the scanner table.
        Coins where price already passed 0 (SL) or already consumed 0.146 are excluded.
        """
        analysis = StrategyManager.get_analysis(symbol, ohlcv, context)
        if not analysis:
            return []

        df = analysis["df"]
        last = df.iloc[-1]
        fib = StrategyManager.compute_fib_levels(df, lookback_window=40, min_impulse_pct=6.0)
        if not fib or not fib.get("valid"):
            return []

        return [{
            "symbol": symbol,
            "price": float(last["close"]),
            "fib_0": fib.get("fib_0", 0.0),
            "fib_0146": fib.get("fib_0146", 0.0),
            "fib_0438": fib.get("fib_0438", 0.0),
            "fib_1": fib.get("fib_1", 0.0),
            "impulse_pct": fib.get("impulse_pct", 0.0),
            "status": fib.get("status", "ACTIVE BIG-MOVE SETUP"),
        }]
