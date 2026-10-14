"""Fair Value Gaps (3-candle imbalance), known at the close of the 3rd candle.

Bullish FVG at bar i: low[i] > high[i-2]  -> zone [high[i-2], low[i]]
Bearish FVG at bar i: high[i] < low[i-2]  -> zone [high[i], low[i-2]]
"""
import pandas as pd


def find_fvgs(df):
    """All FVGs as a DataFrame: direction (+1/-1), bottom, top (indexed by the bar that completes the gap)."""
    h2, l2 = df["high"].shift(2), df["low"].shift(2)
    bull = df["low"] > h2
    bear = df["high"] < l2
    out = pd.DataFrame(index=df.index)
    out["direction"] = 0
    out.loc[bull, "direction"] = 1
    out.loc[bear, "direction"] = -1
    out["bottom"] = h2.where(bull, df["high"].where(bear))
    out["top"] = df["low"].where(bull, l2.where(bear))
    return out[out["direction"] != 0]


def latest_fvg(high, low, start, end, direction, min_size=0.0):
    """Most recent FVG completed in bars [start, end] (inclusive). Returns (bottom, top, bar) or None."""
    for i in range(end, max(start, 2) - 1, -1):
        if direction == 1 and low[i] > high[i - 2] and low[i] - high[i - 2] >= min_size:
            return high[i - 2], low[i], i
        if direction == -1 and high[i] < low[i - 2] and low[i - 2] - high[i] >= min_size:
            return high[i], low[i - 2], i
    return None
