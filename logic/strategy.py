import pandas as pd
import numpy as np


def calculate_ema(series, span):
    if series.empty: return series
    # [HARDENING] Handle NaNs/Infs
    series = series.ffill().fillna(0)
    return series.ewm(span=span, adjust=False).mean()

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss.replace(0, 0.0001))
    return 100 - (100 / (1 + rs))

class StrategyManager:
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
        df['sma200'] = df['close'].rolling(window=200).mean() # SMA is more robust for manual visual sync
        df['rsi'] = calculate_rsi(df['close'], 14)
        
        last = df.iloc[-1]
        
        close_gt_sma200 = float(last['close']) > float(last['sma200'])
        ema50_gt_sma200 = float(last['ema50']) > float(last['sma200'])
        rsi_gt_50 = float(last['rsi']) > 50
        
        reasons = []
        if not close_gt_sma200: reasons.append(f"Price ({last['close']:.0f}) <= SMA200 ({last['sma200']:.0f})")
        if not ema50_gt_sma200: reasons.append(f"EMA50 ({last['ema50']:.0f}) <= SMA200 ({last['sma200']:.0f})")
        if not rsi_gt_50: reasons.append(f"RSI ({last['rsi']:.1f}) <= 50")
        
        btc_pct = (float(last['close']) - float(last['open'])) / float(last['open']) * 100
        
        return {
            "close_gt_ema200": close_gt_sma200, # Keep keys compatible with main.py
            "ema50_gt_ema200": ema50_gt_sma200, 
            "rsi_gt_50": rsi_gt_50,
            "reason": " & ".join(reasons) if reasons else "Bullish",
            "pct_change": float(btc_pct),
            "close": float(last['close']),
            "ema50": float(last['ema50']),
            "ema200": float(last['sma200']), # Mapping to ema200 key
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
        
        return {
            "df": df,
            "qualified": True # Qualification checks moved to check_signal for granularity
        }

    @staticmethod
    def check_signal(symbol, ohlcv, context=None):
        """
        Entry Setup (Disciplined Pullback) - Timeframe: 15M
        
        Conditions:
        1. Price > EMA 50
        2. Higher High structure
        3. Price pulls back toward EMA 20 (Low <= EMA20)
        4. Pullback Low > EMA 50
        5. Bullish Candle Closes > Prev High
        6. RSI > 50
        """
        analysis = StrategyManager.get_analysis(symbol, ohlcv, context)
        if not analysis: return False, {}
            
        df = analysis['df']
        row = df.iloc[-2]      # Trigger Candle (Latest FULLY CLOSED)
        prev_row = df.iloc[-3] # Previous Candle
        
        # ------------------------
        # 1. Price > EMA 50
        # ------------------------
        if row['close'] <= row['ema50']:
            return False, {"reason": "Price <= EMA50 (Not Uptrend)"}

        # ------------------------
        # 2. Higher High Structure
        # ------------------------
        # Check if the swing high of the last 15 candles is higher than the swing high of 15-45 candles ago
        recent_high = df['high'].iloc[-15:-2].max()
        prev_high_period = df['high'].iloc[-45:-15].max()
        
        # Handle case where history is short or nan
        if pd.isna(recent_high) or pd.isna(prev_high_period):
             return False, {"reason": "Insufficient Structure Data"}

        if recent_high <= prev_high_period:
             return False, {"reason": "No Higher High Structure"}

        # ------------------------
        # 3. Pullback toward EMA 20
        # ------------------------
        # We look for interaction with EMA 20 in the last 3 candles
        # "Toward" = Touched or dipped below EMA 20
        # OR Close is very close to EMA 20.
        # Strict Interpretation: Low <= EMA 20 and Low > EMA 50
        # We check the 'prev_row' or current 'row' depending on where the pullback occurred.
        # Often the trigger candle is the bounce. So the pullback happened on prev or prev-prev.
        
        pb_candles = df.iloc[-5:-1] # Look at last 4 candles for the pullback event
        touched_ema20 = (pb_candles['low'] <= pb_candles['ema20']).any()
        
        if not touched_ema20:
             return False, {"reason": "No Pullback to EMA20"}
             
        # ------------------------
        # 4. Pullback Low > EMA 50
        # ------------------------
        # Ensure the lowest point of the pullback respected EMA 50
        min_low_in_pb = pb_candles['low'].min()
        min_ema50_in_pb = pb_candles['ema50'].mean() # Approx
        
        if min_low_in_pb <= min_ema50_in_pb:
             return False, {"reason": "Pullback Violated EMA50"}
             
        # ------------------------
        # 5. Bullish Candle Closes > Prev High
        # ------------------------
        curr_is_bullish = row['close'] > row['open']
        closes_above_prev_high = row['close'] > prev_row['high']
        
        if not (curr_is_bullish and closes_above_prev_high):
             return False, {"reason": "No Bullish Break of Prev High"}
             
        # ------------------------
        # 6. RSI > 50
        # ------------------------
        if row['rsi'] <= 50:
             return False, {"reason": f"RSI Weak ({row['rsi']:.1f} <= 50)"}

        # ------------------------
        # RISK MANAGEMENT
        # ------------------------
        # SL = Below pullback low OR Max 2.5% below entry
        # Use whichever is TIGHTER (Higher Price)
        
        entry_price = row['close']
        pullback_low = pb_candles['low'].min()
        
        # SL Option 1: Structure (Pullback Low)
        sl_structure = pullback_low
        
        # SL Option 2: Max 2.5% Risk
        sl_max_risk = entry_price * 0.975
        
        # Tighter = Higher Price
        sl_price = max(sl_structure, sl_max_risk)
        
        # [Visuals]
        # TP = Fixed 1:2
        risk_per_share = entry_price - sl_price
        if risk_per_share <= 0: return False, {"reason": "Invalid SL Calculation"}
        
        tp_price = entry_price + (risk_per_share * 2)
        
        return True, {
            "signal": "long",
            "sl": sl_price,
            "tp": tp_price, # Strategy defined TP
            "trigger": "Disciplined_PB",
            "reason": "Disciplined Pullback Setup"
        }

    @staticmethod
    def get_scanner_data(symbol, ohlcv, context=None):
        """
        Return visuals: EMA 20, EMA 50 for dashboard.
        """
        analysis = StrategyManager.get_analysis(symbol, ohlcv, context)
        if not analysis: return []
        
        df = analysis['df']
        last = df.iloc[-1]
        
        return [{
            "symbol": symbol,
            "ema20": last['ema20'],
            "ema50": last['ema50'],
            "price": last['close'],
            "rsi": last['rsi']
        }]
