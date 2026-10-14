"""Market structure: BOS (continuation) and CHoCH (change of character).

Bullish break: a candle CLOSES above the last confirmed swing high.
Bearish break: a candle CLOSES below the last confirmed swing low.
If the break is in the direction of the current trend it is a BOS, otherwise a CHoCH.
"""
import numpy as np
import pandas as pd

from goldbot.smc.swings import last_confirmed, swing_points


def market_structure(df, n=2):
    """Returns DataFrame with columns: trend (+1/-1/0), event (BOS_UP, CHOCH_UP, BOS_DOWN, CHOCH_DOWN), level."""
    high, low, close = (df[c].to_numpy(np.float64) for c in ("high", "low", "close"))
    sh, sl = swing_points(high, low, n)
    sh_level, sh_idx = last_confirmed(high, sh, n)
    sl_level, sl_idx = last_confirmed(low, sl, n)

    size = len(df)
    trend = np.zeros(size, dtype=np.int8)
    event = np.full(size, "", dtype=object)
    level = np.full(size, np.nan)
    cur = 0
    used_high = used_low = -1  # a swing can only be broken once
    for t in range(size):
        if sh_idx[t] >= 0 and sh_idx[t] != used_high and close[t] > sh_level[t]:
            event[t] = "BOS_UP" if cur == 1 else "CHOCH_UP"
            level[t] = sh_level[t]
            cur, used_high = 1, sh_idx[t]
        elif sl_idx[t] >= 0 and sl_idx[t] != used_low and close[t] < sl_level[t]:
            event[t] = "BOS_DOWN" if cur == -1 else "CHOCH_DOWN"
            level[t] = sl_level[t]
            cur, used_low = -1, sl_idx[t]
        trend[t] = cur
    return pd.DataFrame({"trend": trend, "event": event, "level": level}, index=df.index)
