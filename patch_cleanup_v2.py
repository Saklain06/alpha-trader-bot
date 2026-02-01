
import os

path = "/opt/gitco/alpha-trader-bot/main.py"

with open(path, "r") as f:
    lines = f.readlines()

new_lines = []
in_block = False
block_buffer = []

# We want to wrap the block starting at "try:" after "[HARDENING] Watcher Safety Cleanup"
# and ending at the end of the except block.

found_header = False
header_index = -1

for i, line in enumerate(lines):
    if "[HARDENING] Watcher Safety Cleanup" in line:
        found_header = True
        header_index = i
        new_lines.append(line)
        continue
    
    if found_header:
        # Check if we are at the "try:" line
        stripped = line.strip()
        if stripped.startswith("try:"):
            # We found the start.
            # Insert our check
            indent = line[:line.find("try:")]
            new_lines.append(f'{indent}if TRADE_MODE == "live":\n')
            
            # Start indenting
            new_lines.append(f"    {line}")
            in_block = True
            found_header = False # Done finding header
            continue
        else:
             new_lines.append(line)
             continue
             
    if in_block:
        # We are inside the Try/Except block. We need to indent everything by 4 spaces.
        # When do we stop?
        # The block ends after the except clause logic.
        # "logger.error(f"[WATCHER CLEANUP ERROR]" is the last line of the except block usually.
        
        new_lines.append(f"    {line}")
        
        if "[WATCHER CLEANUP ERROR]" in line:
            in_block = False
        
        continue

    # Normal line
    new_lines.append(line)

with open(path, "w") as f:
    f.writelines(new_lines)

print("Patch v2 applied.")
