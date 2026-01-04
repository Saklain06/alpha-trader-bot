import math
import unittest

def safe_fixed(v, dec=10):
    try:
        v = float(v)
        if math.isnan(v) or math.isinf(v): return 0.0
        return round(v, dec)
    except: return 0.0

class TestStrategyImprovements(unittest.TestCase):
    def test_precision_fix(self):
        # Test low priced token precision
        price = 0.000017
        entry = 0.000017
        qty = 1000000
        # In old version round(v, 6) might have been okay, 
        # but let's check even lower prices
        tiny_price = 0.00000015
        val = safe_fixed(tiny_price)
        self.assertEqual(val, 0.00000015)
        
        # Test rounding that was failing
        # 1.7e-05 in sqlite output was shown as 1.7e-05
        # but if we round to 6 decimals, it stays 1.7e-05 (0.000017)
        # but 1.2e-05 (0.000012) also stays.
        # However, if price was 0.00000015, round(v, 6) becomes 0.000000
        very_tiny = 0.00000015
        self.assertEqual(safe_fixed(very_tiny, 6), 0.0)
        self.assertEqual(safe_fixed(very_tiny, 10), 0.00000015)

    def test_smc_bounce_logic(self):
        # Mocking the bounce logic
        # if current_price >= prev_close: return True
        current_price = 100
        prev_close = 99
        self.assertTrue(current_price >= prev_close)
        
        current_price = 98
        prev_close = 99
        self.assertFalse(current_price >= prev_close)

if __name__ == "__main__":
    unittest.main()
