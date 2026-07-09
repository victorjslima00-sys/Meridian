import re

with open('app/main.py', 'r') as f:
    content = f.read()

# Fix redefinition of get_current_price
content = re.sub(r'from \.data\.feed import get_current_price', '', content)
content = "from .data.feed import get_current_price\n" + content

# Fix ambiguous variable names (l to lvl)
content = content.replace("for l in range(3):", "for lvl in range(3):")
content = content.replace("bids.append([float(lvl.price), l * 100])", "bids.append([float(DOM_DATA[0].price), lvl * 100])")

with open('app/main.py', 'w') as f:
    f.write(content)
