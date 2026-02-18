
import os
import re

path = "/opt/gitco/alpha-trader-bot/main.py"

with open(path, "r") as f:
    content = f.read()

# 1. Remove unused numpy import
content = content.replace("# import numpy as np # Unused", "")

# 2. Clean up redundant logging header
content = content.replace("""# ------------------------
# LOGGING
# ------------------------
# ------------------------
# LOGGING (ROTATING)
# ------------------------""", """# ------------------------
# LOGGING (ROTATING)
# ------------------------""")

# 3. Remove "NEW" and "FIX" tags to clean up production code
content = re.sub(r'# \[(NEW|FIX|HARDENING|QUANT|RULE|SCALPER MODE|STRATEGY|QUANT UPDATES|VISIBILITY|SYNC)\] ', '# ', content)

# 4. Remove multiple blank lines
content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)

with open(path, "w") as f:
    f.writelines(content)

print("Main.py optimized.")
