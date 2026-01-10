import pandas as pd
import numpy as np

def find_fvgs(df):
    """
    Identifies Fair Value Gaps (FVG) in the dataframe.
    A bullish FVG: low[i+2] > high[i]
    A bearish FVG: high[i+2] < low[i]
    """
    fvgs = []
    for i in range(len(df) - 2):
        # Bullish FVG
        if df['low'].iloc[i+2] > df['high'].iloc[i]:
            fvgs.append({
                'index': i+1,
                'type': 'bullish',
                'top': df['low'].iloc[i+2],
                'bottom': df['high'].iloc[i],
                'mitigated': False
            })
        # Bearish FVG
        elif df['high'].iloc[i+2] < df['low'].iloc[i]:
            fvgs.append({
                'index': i+1,
                'type': 'bearish',
                'top': df['low'].iloc[i],
                'bottom': df['high'].iloc[i+2],
                'mitigated': False
            })
    return fvgs

def find_order_blocks(df, fvgs):
    """
    Identifies Order Blocks (OB) based on detected FVGs.
    A bullish OB is the last bearish candle before a bullish move with FVG.
    A bearish OB is the last bullish candle before a bearish move with FVG.
    """
    obs = []
    for fvg in fvgs:
        idx = fvg['index']
        if fvg['type'] == 'bullish':
            search_idx = idx - 1
            while search_idx >= 0:
                if df['close'].iloc[search_idx] < df['open'].iloc[search_idx]:
                    obs.append({
                        'index': int(search_idx),
                        'type': 'bullish',
                        'top': float(df['high'].iloc[search_idx]),
                        'bottom': float(df['low'].iloc[search_idx]),
                        'mitigated': False
                    })
                    break
                search_idx -= 1
        else:
            search_idx = idx - 1
            while search_idx >= 0:
                if df['close'].iloc[search_idx] > df['open'].iloc[search_idx]:
                    obs.append({
                        'index': int(search_idx),
                        'type': 'bearish',
                        'top': float(df['high'].iloc[search_idx]),
                        'bottom': float(df['low'].iloc[search_idx]),
                        'mitigated': False
                    })
                    break
                search_idx -= 1
    return obs

class SMCManager:
    @staticmethod
    def get_analysis(symbol, ohlcv):
        if not ohlcv or len(ohlcv) < 50:
            return None
        
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
        fvgs = find_fvgs(df)
        obs = find_order_blocks(df, fvgs)
        
        # Filter for unmitigated OBs
        for ob in obs:
            # Check if any candle after OB index has broken the OB
            # Mitigation: A BULLISH OB is mitigated/broken if price closes BELOW the bottom.
            # A BEARISH OB is mitigated/broken if price closes ABOVE the top.
            for j in range(ob['index'] + 1, len(df)):
                close = df['close'].iloc[j]
                if ob['type'] == 'bullish':
                    if close < ob['bottom']:
                        ob['mitigated'] = True
                        break
                else:
                    if close > ob['top']:
                        ob['mitigated'] = True
                        break
        
        active_obs = [ob for ob in obs if not ob['mitigated']]
        # Sort by proximity to current price for the scanner
        df_last = df.iloc[-1]
        active_obs.sort(key=lambda x: abs(x['top'] - df_last['close']) if x['type'] == 'bullish' else abs(x['bottom'] - df_last['close']))
        
        return df, active_obs

    @staticmethod
    def check_signal(symbol: str, ohlcv: list, trend_bullish: bool = True) -> tuple:
        """
        SMC Sniper Entry Signal:
        - Price enters a Bullish Order Block (unmitigated)
        - Close stays above OB bottom
        - [NEW] Major Trend must be Bullish (Price > EMA50)
        """
        try:
            analysis = SMCManager.get_analysis(symbol, ohlcv)
            if not analysis: return False, None
            
            df, active_obs = analysis
            if len(df) < 50: return False, None

            # [QUANT] RSI Calculation (Moved UP for Diagnostics)
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / (loss.replace(0, 0.0001))
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1]
            current_price = df.iloc[-1]['close']

            # [QUANT] Volatility Check (Moved Up for Diagnostics)
            from logic.indicators import check_volatility_ok
            vol_ok, vol_msg = check_volatility_ok(df, '15m')
            
            # Prepare Diagnostic Object EARLY
            diag = {
                "symbol": symbol,
                "strategy": "SMC",
                "active_obs": len(active_obs),
                "nearest_ob": None,
                "rsi": round(current_rsi, 2),
                "trend": "Bullish" if trend_bullish else "Bearish", 
                "price": current_price,
                "vol_ok": vol_ok,
                "vol_msg": vol_msg,
                "reason": ""
            }
            
            # [QUANT] Trend Filter (Avoid catching falling knives)
            if not trend_bullish:
                diag['reason'] = "Trend is Bearish (Price < EMA50)"
                return False, diag
            
            # [QUANT] Volatility Check Rejection
            if not vol_ok:
                diag['reason'] = vol_msg
                return False, diag

            # Reject if RSI is too high (approaching blocked/resistance)
            if current_rsi > 60:
                diag['reason'] = f"RSI Too High ({current_rsi:.1f} > 60)"
                return False, diag

            current_low = df.iloc[-1]['low']
            current_close = df.iloc[-1]['close']

            # Look for entry into a Bullish OB
            bullish_obs = [ob for ob in active_obs if ob['type'] == 'bullish']
            for ob in bullish_obs:
                # Is price inside the OB?
                safety_margin = (ob['top'] - ob['bottom']) * 0.1
                # [QUANT] Confirmation: Current CLOSE must be above entry zone (bounce)
                # and price must have touched the OB top
                if current_low <= ob['top'] and current_close > (ob['bottom'] + safety_margin):
                    # Check for a slight tick up (prevents catching a falling knife)
                    prev_close = df.iloc[-2]['close']
                    if current_close > prev_close: # Confirmation tick up
                        diag["nearest_ob"] = ob['top']
                        return True, diag
            
            if bullish_obs:
                nearest = min(bullish_obs, key=lambda x: abs(x['top'] - current_price))
                diag["nearest_ob"] = nearest['top']
                diag["reason"] = "Approaching OB"
            else:
                diag["reason"] = "No Bullish OB"

            return False, diag
            
        except Exception as e:
            return False, None

    @staticmethod
    def get_scanner_data(symbol, ohlcv):
        try:
            analysis = SMCManager.get_analysis(symbol, ohlcv)
            if not analysis: return None
            
            df, active_obs = analysis
            current_price = df.iloc[-1]['close']
            
            scanner_items = []
            for ob in active_obs:
                distance = round(((ob['top'] if ob['type'] == 'bullish' else ob['bottom']) - current_price) / current_price * 100, 2)
                scanner_items.append({
                    "symbol": symbol,
                    "type": ob['type'],
                    "top": ob['top'],
                    "bottom": ob['bottom'],
                    "distance_pct": distance,
                    "price": current_price
                })
            
            # [UI FIX] Filter for BULLISH OBs only (Demand Zones)
            # The bot is Spot Long-Only, so showing Bearish OBs (Resistance) as "scanner results" 
            # confuses users who expect "Entry Signals".
            scanner_items = [item for item in scanner_items if item['type'] == 'bullish']

            # [DEDUPLICATION] Return only the single closest OB per coin
            if scanner_items:
                scanner_items.sort(key=lambda x: abs(x['distance_pct']))
                return [scanner_items[0]]
                
            return []
        except:
            return None
