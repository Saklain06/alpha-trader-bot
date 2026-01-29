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
