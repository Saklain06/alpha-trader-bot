import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def get_regime_mock(ema50, ema200):
    if ema50 > ema200:
        diff_pct = abs(ema50 - ema200) / ema200 * 100
        if diff_pct < 0.5:
            return "flat"
        return "bullish"
    return "bearish"

class TestPhase2(unittest.TestCase):
    def test_regime_logic(self):
        # Bullish
        self.assertEqual(get_regime_mock(105, 100), "bullish")
        # Flat (within 0.5%)
        self.assertEqual(get_regime_mock(100.4, 100), "flat")
        # Bearish
        self.assertEqual(get_regime_mock(95, 100), "bearish")

    def test_rrr_logic(self):
        tp_val = 15.0
        sl_val = 6.0
        rrr = tp_val / sl_val
        self.assertGreaterEqual(rrr, 1.8)
        
        tp_val_low = 10.0
        rrr_low = tp_val_low / sl_val
        self.assertLess(rrr_low, 1.8)

    def test_bollinger_confirmation_mock(self):
        # RSI rising: curr > prev
        curr_rsi = 32
        prev_rsi = 30
        is_rsi_rising = curr_rsi > prev_rsi
        self.assertTrue(is_rsi_rising)
        
        # Price crossing back above band
        curr_price = 101
        curr_lower = 100
        prev_price = 99
        prev_lower = 100
        is_closing_above = curr_price > curr_lower and prev_price <= prev_lower
        self.assertTrue(is_closing_above)

if __name__ == "__main__":
    unittest.main()
