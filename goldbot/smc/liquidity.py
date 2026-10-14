"""Liquidity pools. The Asian range high/low is where buy-side / sell-side stops rest."""
import numpy as np
import pandas as pd


def asian_range(df, sess, min_bars=24):
    """Per session day: asian_high, asian_low, end_pos (position of the last Asian bar)."""
    pos = pd.Series(np.arange(len(df)), index=df.index)
    m = sess["asian"].to_numpy()
    g = pd.DataFrame(
        {"high": df["high"][m], "low": df["low"][m], "pos": pos[m], "day": sess["session_day"][m]}
    ).groupby("day")
    out = pd.DataFrame(
        {"asian_high": g["high"].max(), "asian_low": g["low"].min(), "end_pos": g["pos"].max(), "bars": g["pos"].count()}
    )
    return out[out["bars"] >= min_bars]
