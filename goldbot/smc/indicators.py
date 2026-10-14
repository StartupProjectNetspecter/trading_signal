import numpy as np
import pandas as pd


def atr(df, period=14):
    """Wilder's Average True Range."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def to_np(df):
    return (
        df["open"].to_numpy(np.float64),
        df["high"].to_numpy(np.float64),
        df["low"].to_numpy(np.float64),
        df["close"].to_numpy(np.float64),
    )
