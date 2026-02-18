
import os
import re

path = "/opt/gitco/alpha-trader-bot/main.py"

with open(path, "r") as f:
    content = f.read()

# 1. Update execute_buy (Paper)
# Current:
#         # Paper
#         exec_price = price
#         qty = safe(usd / price)
#         used = safe(qty * exec_price)
#         fees = safe(used * COMMISSION_PCT)
#         if not sl and sl_pct: sl = safe(exec_price * (1 - sl_pct / 100))
#         if not tp and tp_pct: tp = safe(exec_price * (1 + tp_pct / 100))

buy_pattern = r'# Paper\n\s+exec_price = price\n\s+qty = safe\(usd / price\)\n\s+used = safe\(qty \* exec_price\)\n\s+fees = safe\(used \* COMMISSION_PCT\)'
buy_replacement = """# Paper (Binance-Style Fee Alignment)
        exec_price = price
        fees = safe(usd * COMMISSION_PCT)
        qty = safe((usd / price) * (1 - COMMISSION_PCT)) # Fee deducted from asset
        used = usd # Porton of USDT wallet spent"""

content = re.sub(buy_pattern, buy_replacement, content)

# 2. Update execute_sell PnL formula (Paper)
# Current:
#         pnl = safe((exec_price - trade['entry_price']) * sell_qty - fees)
sell_pnl_pattern = r'pnl = safe\(\(exec_price - trade\[\'entry_price\'\]\) \* sell_qty - fees\)'
sell_pnl_replacement = "pnl = safe((exec_price * sell_qty) - (trade['used_usd'] * (sell_qty / trade['qty'])) - fees)"

content = re.sub(sell_pnl_pattern, sell_pnl_replacement, content)

# 3. Update unrealized_pnl in watcher_loop
# Current:
#                     unreal = (price - t['entry_price']) * t['qty']
unreal_pattern = r'unreal = \(price - t\[\'entry_price\'\]\) \* t\[\'qty\'\]'
unreal_replacement = "unreal = (price * t['qty']) - t['used_usd']"

content = re.sub(unreal_pattern, unreal_replacement, content)

with open(path, "w") as f:
    f.write(content)

print("Paper fee alignment applied.")
