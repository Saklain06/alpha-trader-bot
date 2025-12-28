import pandas as pd
import logging

logger = logging.getLogger("TradingBot")

class AlphaHunter:
    @staticmethod
    def check_signal(symbol: str, ohlcv: list) -> bool:
        """
        Analyzes 1H candles to find 'Pre-Pump' signatures:
        1. Tight Consolidation (< 10% range in 24h)
        2. high Volume Spike (> 3x 24h avg)
        3. Low Price Change (< 5% in 24h)
        """
        try:
            if not ohlcv or len(ohlcv) < 24: return False
            
            df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            
            # 1. Check Consolidation (Last 24h)
            last_24 = df.iloc[-24:]
            high = last_24['high'].max()
            low = last_24['low'].min()
            if low <= 0: return False
            
            price_range = ((high - low) / low) * 100
            
            if price_range > 10.0: return False # Too volatile
                
            # 2. Check Volume Spike (Last 1h vs Avg 24h)
            current_vol = df.iloc[-1]['vol']
            avg_vol = last_24['vol'].mean()
            
            if avg_vol == 0: return False
            vol_mult = current_vol / avg_vol
            
            if vol_mult < 3.0: return False # No whale activity
                
            # 3. Check Price Change (Don't buy top)
            open_24 = last_24.iloc[0]['open']
            close_now = df.iloc[-1]['close']
            change = ((close_now - open_24) / open_24) * 100
            
            if change > 5.0: return False # Already pumped
            
            logger.info(f"[ALPHA FOUND] {symbol} | Vol: {vol_mult:.1f}x | Range: {price_range:.1f}%")
            return True
            
        except Exception as e:
            logger.error(f"[STRATEGY ERROR] {symbol}: {e}")
            return False
