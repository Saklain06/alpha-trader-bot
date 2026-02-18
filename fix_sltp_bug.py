
path = "/opt/gitco/alpha-trader-bot/main.py"

with open(path, "r") as f:
    lines = f.readlines()

new_lines = []
target_found = False

for i in range(len(lines)):
    line = lines[i]
    if "# Paper" in line and i + 5 < len(lines):
        # Look for the sl/tp assignments in the next few lines
        if "sl = safe(exec_price * (1 - sl_pct / 100)) if sl_pct else 0.0" in lines[i+5]:
            # Replace lines i+5 and i+6
            # Original:
            # sl = safe(exec_price * (1 - sl_pct / 100)) if sl_pct else 0.0
            # tp = safe(exec_price * (1 + tp_pct / 100)) if tp_pct else 0.0
            
            indent = lines[i+5][:lines[i+5].find("sl =")]
            lines[i+5] = f"{indent}if not sl and sl_pct: sl = safe(exec_price * (1 - sl_pct / 100))\n"
            lines[i+6] = f"{indent}if not tp and tp_pct: tp = safe(exec_price * (1 + tp_pct / 100))\n"
            target_found = True

if target_found:
    with open(path, "w") as f:
        f.writelines(lines)
    print("Patch applied.")
else:
    print("Target block not found.")
