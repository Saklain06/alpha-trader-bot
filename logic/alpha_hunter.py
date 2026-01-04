import pandas as pd
import logging

logger = logging.getLogger("TradingBot")

class AlphaHunter:
    @staticmethod
    def check_signal(symbol: str, ohlcv: list) -> tuple:
        """
        Analyzes 1H candles to find 'Pre-Pump' signatures:
        Returns (bool signal, dict diagnostic)
        """
        try:
            if not ohlcv or len(ohlcv) < 24: return False, None
            
            df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            
            # [QUANT] Volatility Check
            from logic.indicators import check_volatility_ok
            vol_ok, vol_msg = check_volatility_ok(df, '1h')
            if not vol_ok:
                return False, {"reason": vol_msg}
            
            # 1. Check Consolidation (Last 24h)
            last_24 = df.iloc[-24:]
            high = last_24['high'].max()
            low = last_24['low'].min()
            if low <= 0: return False, None
            
            price_range = round(((high - low) / low) * 100, 2)
            
            diag = {
                "symbol": symbol,
                "range": price_range,
                "vol_mult": 0.0,
                "change": 0.0,
                "reason": ""
            }

            if price_range > 15.0: # Allow slightly wider range for diagnostics
                return False, None
                
            # 2. Check Volume Spike (Last 1h vs Avg 24h)
            current_vol = df.iloc[-1]['vol']
            avg_vol = last_24['vol'].mean()
            
            if avg_vol == 0: return False, None
            vol_mult = round(current_vol / avg_vol, 2)
            diag["vol_mult"] = vol_mult
            
            # 3. Calculate Indicators
            # RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            curr_rsi = round(rsi.iloc[-1], 2)
            
            # EMA 8 (Trend)
            ema8 = df['close'].ewm(span=8, adjust=False).mean()
            curr_ema8 = ema8.iloc[-1]
            
            # 4. Check Price Change (Don't buy top)
            open_24 = last_24.iloc[0]['open']
            close_now = df.iloc[-1]['close']
            change = round(((close_now - open_24) / open_24) * 100, 2)
            diag["change"] = change

            # Logic Check
            is_range_ok = price_range <= 10.0
            is_vol_ok = vol_mult >= 4.0
            is_change_ok = change <= 5.0
            is_rsi_ok = curr_rsi < 70
            is_trend_ok = close_now > curr_ema8

            if is_range_ok and is_vol_ok and is_change_ok and is_rsi_ok and is_trend_ok:
                logger.info(f"[ALPHA FOUND] {symbol} | Vol: {vol_mult}x | RSI: {curr_rsi} | Range: {price_range}%")
                # Return 15% TP for Alpha Hunter
                diag['tp_pct'] = 15.0
                return True, diag
            
            # If "Interesting" but not a signal (Near Hit)
            if (vol_mult > 1.5 or price_range < 5.0) and change < 10:
                if not is_rsi_ok: diag["reason"] = "Overbought"
                elif not is_trend_ok: diag["reason"] = "No Trend"
                else: diag["reason"] = "Low Vol" if not is_vol_ok else "Volatile" if not is_range_ok else "Pumped"
                return False, diag

            return False, None
            
        except Exception as e:
            logger.error(f"[STRATEGY ERROR] {symbol}: {e}")
            return False, None
            
        except Exception as e:
            logger.error(f"[STRATEGY ERROR] {symbol}: {e}")
            return False
