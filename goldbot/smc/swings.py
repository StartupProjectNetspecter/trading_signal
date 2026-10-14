"""Swing highs / lows (fractals).

A swing high at bar j is the highest high of bars [j-n, j+n]. It can only be KNOWN after
bar j+n closes, so every "last swing" lookup here uses the confirmation bar, never j itself.
This is what prevents repainting / look-ahead in backtests.
"""
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view


def swing_points(high, low, n):
    """Boolean arrays marking pivot bars (at the pivot index j, not the confirmation index)."""
    size = len(high)
    sh = np.zeros(size, dtype=bool)
    sl = np.zeros(size, dtype=bool)
    if size < 2 * n + 1:
        return sh, sl
    w = 2 * n + 1
    hw = sliding_window_view(high, w)
    lw = sliding_window_view(low, w)
    # pivot must be the first occurrence of the window extreme (handles equal highs/lows)
    sh[n : size - n] = np.argmax(hw, axis=1) == n
    sl[n : size - n] = np.argmin(lw, axis=1) == n
    return sh, sl


def last_confirmed(values, pivots, n):
    """For each bar t: (level, pivot_index) of the most recent pivot confirmed by bar t (j + n <= t)."""
    size = len(values)
    level = np.full(size, np.nan)
    index = np.full(size, -1, dtype=np.int64)
    for j in np.flatnonzero(pivots):
        t = j + n
        if t < size:
            level[t] = values[j]
            index[t] = j
    # forward-fill
    mask = index >= 0
    pos = np.where(mask, np.arange(size), 0)
    np.maximum.accumulate(pos, out=pos)
    has = np.maximum.accumulate(mask)
    level = np.where(has, level[pos], np.nan)
    index = np.where(has, index[pos], -1)
    return level, index
