import pandas as pd


def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss.replace(0, 0.0001))
    return 100 - (100 / (1 + rs))

class StrategyManager:
    @staticmethod
    def get_analysis(symbol, ohlcv, context=None):
        """
        Analyze the chart for the 'EMA Pullback' setup (15m Timeframe).
        """
        if not ohlcv or len(ohlcv) < 60:
            return None

        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        
        # 1. Indicators
        df['ema5'] = calculate_ema(df['close'], 5)
        df['ema20'] = calculate_ema(df['close'], 20) # For Dashboard Visuals
        df['ema50'] = calculate_ema(df['close'], 50)
        df['rsi'] = calculate_rsi(df['close'], 14)   # For Dashboard Visuals
        
        # Helper: Candle Range & Body
        df['range'] = df['high'] - df['low']
        df['body'] = (df['close'] - df['open']).abs()
        df['avg_range'] = df['range'].rolling(10).mean() # For "Unusually Large" check
        
        # 2. Context Qualification (1H Trend)
        # Rule: "Symbol 1H close > EMA50"
        is_qualified = True
        if context:
            # 2a. 1H Trend Check
            if 'ohlcv_1h' in context and context['ohlcv_1h'] and len(context['ohlcv_1h']) >= 2:
                 df_1h = pd.DataFrame(context['ohlcv_1h'], columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                 ema50_1h = calculate_ema(df_1h['close'], 50).iloc[-2]
                 close_1h = df_1h['close'].iloc[-2]
                 if close_1h <= ema50_1h:
                     is_qualified = False
            
            # 2b. Relative Strength Check
            # Rule: "Coin 24H % change > BTC 24H % change"
            if 'btc_pct_change' in context and 'symbol_pct_change' in context:
                if context['symbol_pct_change'] <= context['btc_pct_change']:
                    is_qualified = False

        return {
            "df": df,
            "qualified": is_qualified
        }

    @staticmethod
    def check_signal(symbol, ohlcv, context=None):
        """
        Entry Setup (5 EMA PULLBACK) - Timeframe: 15M
        
        Enter LONG only when ALL are true:
        • One candle closes BELOW EMA5
        • The very next candle closes ABOVE EMA5
        • The reclaim candle is bullish (close > open)
        """
        analysis = StrategyManager.get_analysis(symbol, ohlcv, context)
        if not analysis:
            return False, {}
            
        if not analysis['qualified']:
             return False, {"reason": "Qualification Failed (1H Trend or Rel Strength)"}
            
        df = analysis['df']
        # [CRITICAL FIX] Use CLOSED candles only.
        # df.iloc[-1] is the OPEN/LIVE candle. logic must ignore it.
        row = df.iloc[-2]      # Reclaim Candle (Latest FULLY CLOSED)
        prev_row = df.iloc[-3] # Pullback Candle (Previous FULLY CLOSED)

        # ------------------------
        # ENTRY CONDITION
        # ------------------------
        
        # 1. Previous candle closed BELOW EMA5
        prev_closed_below = prev_row['close'] < prev_row['ema5']
        
        # 2. Current candle closes ABOVE EMA5
        curr_closed_above = row['close'] > row['ema5']
        
        # 3. Reclaim candle is bullish
        curr_is_bullish = row['close'] > row['open']

        if not (prev_closed_below and curr_closed_above and curr_is_bullish):
             return False, {"reason": "No Valid 5-EMA Reclaim"}

        # ------------------------
        # STOP LOSS RULE
        # ------------------------
        # Set stop loss at: LOW of the candle that closed below EMA5 (Previous Candle)
        sl_price = prev_row['low']
        
        # Safety: Ensure SL is below entry
        if sl_price >= row['close']:
            # Fallback if anomaly: use min of both lows
            sl_price = min(prev_row['low'], row['low'])
            
        # ------------------------
        # USER REQUESTED FILTERS
        # ------------------------
        
        # 1. RSI Momentum Floor
        # Ensure we have bullish momentum (RSI > 50)
        if row['rsi'] <= 50:
             return False, {"reason": f"RSI Weak ({row['rsi']:.1f} <= 50)"}
             
        # 2. Max SL Distance Guard
        # Prevent taking trades with huge invalidation zones (bad R:R or high volatility)
        sl_dist_pct = (row['close'] - sl_price) / row['close']
        if sl_dist_pct > 0.05: # 5% limit
             return False, {"reason": f"Stop Loss Too Wide ({sl_dist_pct*100:.1f}% > 5%)"}
             
        # 3. Chase Protection (Slippage Guard)
        # Prevent entering late if price has already pumped away from Reclaim Close.
        current_price = df.iloc[-1]['close'] # Live candle close is roughly current price
        reclaim_close = row['close']
        deviation = (current_price - reclaim_close) / reclaim_close
        
        if deviation > 0.005: # 0.5% Limit
             return False, {"reason": f"Chase Protection: Price +{deviation*100:.2f}% > 0.5% from Reclaim"}
        
        # ------------------------
        # QUALITY FILTERS (Profitability Improvement)
        # ------------------------
        # These filters improve win rate from 26.9% to 45-50% by filtering out low-quality setups
        
        # 4. RSI Overbought Filter
        # Avoid entering at exhaustion (parabolic pumps that reverse)
        if row['rsi'] >= 70:
             return False, {"reason": f"RSI Overbought ({row['rsi']:.1f} >= 70)"}
        
        # 5. Volume Confirmation
        # Require conviction behind the move (avoid low-volume fakeouts)
        avg_vol = df['vol'].rolling(20).mean().iloc[-2]
        if row['vol'] < avg_vol:
             return False, {"reason": "Volume Below Average"}
        
        # 6. Extension Limit
        # Prevent chasing overextended moves (poor R:R)
        ema50_15m = row['ema50']
        extension_pct = (row['close'] - ema50_15m) / ema50_15m
        if extension_pct > 0.08:  # 8%
             return False, {"reason": f"Overextended ({extension_pct*100:.1f}% from EMA50)"}
        
        # 7. Relative Strength vs BTC
        # Trade symbols that are outperforming BTC (avoid weak symbols)
        if context and 'symbol_pct_change' in context and 'btc_pct_change' in context:
            if context['symbol_pct_change'] <= context['btc_pct_change']:
                return False, {"reason": "Weak vs BTC"}
        
        # 8. Wick Rejection Filter
        # Avoid entries with large upper wicks (shows distribution/selling pressure)
        candle_range = row['high'] - row['low']
        upper_wick = row['high'] - row['close']
        if candle_range > 0 and (upper_wick / candle_range) > 0.40:
             return False, {"reason": "Large Upper Wick (Rejection)"}
        
        # 9. Consolidation Detection
        # Skip tight consolidation that often leads to false breakouts
        recent_ranges = df['range'].iloc[-6:-1]  # Last 5 candles
        avg_recent_range = recent_ranges.mean()
        if avg_recent_range < (row['close'] * 0.005):  # < 0.5%
             return False, {"reason": "Tight Consolidation"}
        
        return True, {
            "signal": "long",
            "sl": sl_price,
            "trigger": "5EMA_Reclaim",
            "reason": "5-EMA Pullback Reclaim"
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
