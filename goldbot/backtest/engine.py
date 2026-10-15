"""Bar-by-bar simulation of limit-order signals on M5 BID candles.

Conservative assumptions:
  * BUY fills when ASK (bid + spread) touches entry; exits on BID. SELL is the mirror.
  * On the fill bar only the stop is checked (we cannot know if TP came first).
  * If stop and target are both touched in one bar, the stop wins.
  * If price reaches TP before the order fills, the order is cancelled.
  * Break-even / partial take-profit only trigger from the bar AFTER the fill, and a
    break-even stop only becomes active on the bar after it was earned.
"""
import numpy as np
import pandas as pd

from goldbot.smc.indicators import to_np


def simulate(signals, m5, cfg):
    bt = cfg["backtest"]
    spread, max_hold = bt["spread_usd"], bt["max_hold_bars"]
    st = cfg["strategy"]
    be_r, part_r = st.get("breakeven_at_r"), st.get("partial_at_r")
    part_frac = st.get("partial_frac", 0.5)
    idx = m5.index
    o, h, l, c = to_np(m5)
    n = len(idx)
    rows = []
    for s in signals.to_dict("records"):
        d = 1 if s["direction"] == "BUY" else -1
        entry, sl, tp = s["entry"], s["sl"], s["tp"]
        start = idx.searchsorted(s["signal_time"])
        expiry = min(idx.searchsorted(s["expiry_time"]), n)

        fill_j, fill_px, outcome = None, None, "expired"
        if s.get("order") == "market" and start < n:  # filled at the next bar's open
            fill_j = start
            fill_px = o[start] + spread if d == 1 else o[start]
            expiry = start  # skip the limit-order loop
        for j in range(start, expiry):
            if d == 1 and l[j] + spread <= entry:
                fill_j, fill_px = j, min(entry, o[j] + spread)
            elif d == -1 and h[j] >= entry:
                fill_j, fill_px = j, max(entry, o[j])
            if fill_j is not None:
                break
            if (d == 1 and h[j] >= tp) or (d == -1 and l[j] + spread <= tp):
                outcome = "cancelled"
                break

        rec = dict(s, filled=fill_j is not None, fill_time=pd.NaT, exit_time=pd.NaT, exit_price=np.nan, r=np.nan)
        if fill_j is None:
            rec["outcome"] = "no_fill_" + outcome
            rows.append(rec)
            continue

        exit_j, exit_px, outcome = None, None, "time"
        risk = (fill_px - sl) * d
        stop, size, banked = sl, 1.0, 0.0  # banked = price P&L already locked by a partial close
        be_px = fill_px + d * be_r * risk if be_r else None
        part_px = fill_px + d * part_r * risk if part_r else None
        last = min(fill_j + max_hold, n - 1)
        for j in range(fill_j, last + 1):
            # prices the position is closed against: BID for longs, ASK for shorts
            lo, hi, op = (l[j], h[j], o[j]) if d == 1 else (l[j] + spread, h[j] + spread, o[j] + spread)
            if (lo <= stop) if d == 1 else (hi >= stop):
                exit_j, outcome = j, "sl" if stop == sl else "be"
                exit_px = stop if j == fill_j else (min(stop, op) if d == 1 else max(stop, op))  # gap through
                break
            if j == fill_j:
                continue  # conservative: no profit-taking on the fill bar
            best = hi if d == 1 else lo
            if part_px is not None and size == 1.0 and (best - part_px) * d >= 0:
                banked += part_frac * (part_px - fill_px) * d
                size -= part_frac
            if (best - tp) * d >= 0:
                exit_j, exit_px, outcome = j, tp, "tp"
                break
            if be_px is not None and (best - be_px) * d >= 0:
                stop = fill_px  # takes effect from the next bar
        if exit_j is None:
            exit_j = last
            exit_px = c[last] if d == 1 else c[last] + spread

        pnl = banked + size * (exit_px - fill_px) * d
        fees = bt.get("commission_pct", 0.0) / 100 * (fill_px + exit_px)  # per-side % fee, entry + exit
        rec.update(
            fill_time=idx[fill_j],
            fill_price=round(fill_px, 2),
            exit_time=idx[exit_j] + pd.Timedelta(minutes=5),
            exit_price=round(exit_px, 2),
            outcome=outcome + ("+partial" if size < 1.0 else ""),
            r=round((pnl - fees) / risk, 3),
        )
        rows.append(rec)
    return pd.DataFrame(rows)
