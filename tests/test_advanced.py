import math
import unittest
from datetime import datetime, timedelta

def safe_fixed(v, dec=10):
    try:
        v = float(v)
        if math.isnan(v) or math.isinf(v): return 0.0
        return round(v, dec)
    except: return 0.0

class TestAdvancedImprovements(unittest.TestCase):
    def test_exit_logic_breakeven(self):
        # Mock logic
        entry_price = 100
        current_price = 101.3 # +1.3%
        sl = 95
        
        gain_pct = ((current_price - entry_price) / entry_price) * 100
        if gain_pct >= 1.2 and sl < entry_price:
            sl = entry_price
        
        self.assertEqual(sl, 100)

    def test_exit_logic_trailing(self):
        entry_price = 100
        highest_price = 102.5 # +2.5%
        trail_sl = 0
        trail_active = False
        
        gain_pct = ((highest_price - entry_price) / entry_price) * 100
        if gain_pct >= 2.0:
            trail_active = True
            trail_sl = safe_fixed(highest_price * (1 - 0.012)) # 1.2% distance
            
        self.assertTrue(trail_active)
        self.assertEqual(trail_sl, safe_fixed(102.5 * 0.988))

    def test_cooldown_logic(self):
        last_ts = datetime.now().timestamp() - (2 * 3600) # 2 hours ago
        cooldown_sec = 4 * 3600
        
        is_cooldown = (datetime.now().timestamp() - last_ts) < cooldown_sec
        self.assertTrue(is_cooldown)
        
        last_ts_old = datetime.now().timestamp() - (5 * 3600) # 5 hours ago
        is_cooldown_old = (datetime.now().timestamp() - last_ts_old) < cooldown_sec
        self.assertFalse(is_cooldown_old)

if __name__ == "__main__":
    unittest.main()
