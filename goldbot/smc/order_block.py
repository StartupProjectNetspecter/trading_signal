"""Order Blocks: the last opposite-colour candle before the displacement that broke structure.

Bullish OB = last bearish candle (close < open) between the sweep extreme and the CHoCH candle.
Bearish OB = last bullish candle (close > open) in the same window.
"""


def find_order_block(open_, high, low, close, start, end, direction):
    """Search bars [start, end) backwards. Returns (bottom, top, bar) or None."""
    for k in range(end - 1, start - 1, -1):
        if direction == 1 and close[k] < open_[k]:
            return low[k], high[k], k
        if direction == -1 and close[k] > open_[k]:
            return low[k], high[k], k
    return None
