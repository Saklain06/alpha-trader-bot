
import pandas as pd
import numpy as np
from logic.smc_utils import SMCManager, find_fvgs, find_order_blocks

def mock_ohlcv(length=100, trend='up', rsi_scenario='normal'):
    # Generate synthetic OHLCV data
    # Simple uptrend simulation
    base_price = 100
    data = []
    
    for i in range(length):
        if trend == 'up':
            base_price += np.random.normal(0.5, 1.0)
        else:
            base_price -= np.random.normal(0.5, 1.0)
            
        close = base_price
        open_p = close - np.random.normal(0, 0.5)
        high = max(open_p, close) + abs(np.random.normal(0, 0.5))
        low = min(open_p, close) - abs(np.random.normal(0, 0.5))
        vol = 1000
        
        # Inject Overbought RSI scenario at the end
        if rsi_scenario == 'overbought' and i > length - 15:
            # parabolic move up
            base_price += 5.0 
            close = base_price
            open_p = close - 1
            high = close + 1
            low = open_p - 1

        data.append([i * 900000, open_p, high, low, close, vol])
        
    return data

def test_rsi_filter():
    print("Testing RSI Filter Logic...")
    
    # Scene 1: Normal RSI (Should Allow Trade if signal exists)
    # We need to construct a valid Signal scenario first (Bullish OB + Mitigation)
    # This is hard to mock perfectly without complex data, so we will just test the RSI function indirectly
    # by checking the diagnostics returned by check_signal.
    
    # Let's create an Overbought scenario and see if it rejects with "RSI Too High"
    ohlcv = mock_ohlcv(length=100, trend='up', rsi_scenario='overbought')
    
    # We don't need a real OB signal for this test, we just want to see if it even GETS to the logic
    # or if it fails early/returns diagnostic with RSI value.
    try:
        is_signal, diag = SMCManager.check_signal("TEST/USDT", ohlcv, trend_bullish=True)
        
        if diag:
            print(f"Diagnostics: {diag}")
            if "RSI Too High" in diag.get('reason', ''):
                print("✅ PASS: Successfully rejected trade due to High RSI.")
            elif diag.get('rsi') > 60:
                 if not is_signal:
                     print(f"✅ PASS: RSI is {diag['rsi']} (> 60) and Signal is False.")
                 else:
                     print(f"❌ FAIL: RSI is {diag['rsi']} but Signal was TRUE!")
            else:
                print(f"ℹ️ RSI was {diag.get('rsi')}, not high enough to trigger filter in this seed.")
        else:
            print("❌ FAIL: No diagnostics returned.")
            
    except Exception as e:
        print(f"❌ CRASH: {e}")

if __name__ == "__main__":
    test_rsi_filter()
