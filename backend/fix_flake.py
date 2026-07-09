import re

with open('app/main.py', 'r') as f:
    lines = f.readlines()

out = []
for i, line in enumerate(lines):
    # Remove unused imports
    if "import random" in line and "unused" in line: continue
    if "from typing import Dict, Any" in line: continue
    if "from .data.database import get_trades" in line: continue
    # Fix exception variable unused
    if "except Exception as e:" in line:
        line = line.replace("except Exception as e:", "except Exception:")
    if "data = await websocket.receive_text()" in line:
        line = line.replace("data = await websocket.receive_text()", "_ = await websocket.receive_text()")
    if "except:" in line:
        line = line.replace("except:", "except Exception:")
        
    out.append(line)

with open('app/main.py', 'w') as f:
    f.writelines(out)
