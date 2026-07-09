import re

with open('app/main.py', 'r') as f:
    lines = f.readlines()

out = []
for i, line in enumerate(lines):
    # Remove unused imports
    if "import random" in line and "unused" in line: continue
    if "from .data.database import get_trades" in line: continue
    # Fix ambiguous l to level
    if "for l in range(3):" in line:
        line = line.replace("for l in range(3):", "for level in range(3):")
    if "bids.append([float(DOM_DATA[0].price), l * 100])" in line:
        line = line.replace("bids.append([float(DOM_DATA[0].price), l * 100])", "bids.append([float(DOM_DATA[0].price), level * 100])")
    
    out.append(line)

with open('app/main.py', 'w') as f:
    f.writelines(out)
