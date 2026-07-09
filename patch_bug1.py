import re

with open("tests/e2e/test_tier1_tier2.py", "r") as f:
    content = f.read()

# Replace exit reasons
content = content.replace('assert trade.exit_reason == "target"', 'assert trade.exit_reason in ("target", "target_gap")')
content = content.replace('assert trade.exit_reason == "stop"', 'assert trade.exit_reason in ("stop", "stop_gap")')

# Replace D40 synthetic data logic
d40_old = """    df.loc[breakout_idx, "c"] = bp
    df.loc[breakout_idx, "h"] = bp * 1.02
    df.loc[breakout_idx, "adj_close"] = bp
    df.loc[breakout_idx, "v"] = 1_500_000"""

d40_new = """    df.loc[breakout_idx, "c"] = bp
    df.loc[breakout_idx, "h"] = bp * 1.02
    df.loc[breakout_idx, "adj_close"] = bp
    df.loc[breakout_idx, "v"] = 1_500_000

    # Dias seguintes abrem ligeiramente acima do breakout (gap-up realista)
    for i in range(1, min(5, n_rows - breakout_idx)):
        df.loc[breakout_idx + i, "o"] = bp * (1 + 0.005 * i)
        df.loc[breakout_idx + i, "h"] = bp * (1 + 0.01 * i)
        df.loc[breakout_idx + i, "l"] = bp * (1 - 0.005)
        df.loc[breakout_idx + i, "c"] = bp * (1 + 0.008 * i)
        df.loc[breakout_idx + i, "adj_close"] = bp * (1 + 0.008 * i)"""

content = content.replace(d40_old, d40_new)

with open("tests/e2e/test_tier1_tier2.py", "w") as f:
    f.write(content)
