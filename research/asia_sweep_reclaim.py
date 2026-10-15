"""The pasted 'Asia Range Liquidity Sweep' scenario, tested exactly.  python -m research.asia_sweep_reclaim

Asian range high/low -> in the window, a candle pokes outside the range and CLOSES back inside
-> enter at that close (market, next bar open) -> SL just beyond the sweep wick -> TP = range midpoint
or the opposite side. One trade per side per day. M5 and M1. Cost $0.30.
"""
import itertools

import numpy as np
import pandas as pd

from goldbot.backtest.engine import simulate
from goldbot.config import load_config, resolve
from goldbot.data.store import load_m5
from goldbot.smc.indicators import atr
from goldbot.smc.sessions import session_frame
from goldbot.strategy.asian_sweep import _Levels
from research.scalping_test import load_m1

WINDOWS = {"London 1st hour": (120, 180), "London 02-05": (120, 300), "New York 07-10": (420, 600)}


def signals(df, cfg, bar, window, target, buf):
    sess = session_frame(df.index, cfg)
    lv = _Levels(df, sess)
    day = sess["session_day"].to_numpy()
    ah = lv.asian["asian_high"].reindex(day).to_numpy()
    al = lv.asian["asian_low"].reindex(day).to_numpy()
    asian = sess["asian"].to_numpy()
    ny = df.index.tz_convert("America/New_York")
    minute = (ny.hour * 60 + ny.minute).to_numpy()
    news = sess["news_block"].to_numpy()
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = atr(df, 14).to_numpy()
    out, used = [], set()
    for i in np.flatnonzero(~asian & (minute >= window[0]) & (minute < window[1]) & ~news & np.isfinite(ah)):
        for d, swept, back in ((-1, h[i] > ah[i], al[i] < c[i] < ah[i]), (1, l[i] < al[i], al[i] < c[i] < ah[i])):
            if not (swept and back) or (day[i], d) in used:
                continue
            used.add((day[i], d))
            sl = (h[i] + buf * a[i]) if d == -1 else (l[i] - buf * a[i])
            tp = (ah[i] + al[i]) / 2 if target == "midpoint" else (al[i] if d == -1 else ah[i])
            risk, reward = (c[i] - sl) * d, (tp - c[i]) * d
            if risk < 0.5 or reward <= 0:
                continue
            out.append({"signal_time": df.index[i] + bar, "expiry_time": df.index[i] + 2 * bar, "direction": "BUY" if d == 1 else "SELL",
                        "entry": c[i], "sl": sl, "tp": tp, "rr": reward / risk, "order": "market"})
    return pd.DataFrame(out)


def main():
    cfg = load_config()
    data = {"M5": (load_m5(cfg), pd.Timedelta(minutes=5)), "M1": (load_m1(), pd.Timedelta(minutes=1))}
    rows = []
    for (tf, (df, bar)), (wname, win), target, buf in itertools.product(data.items(), WINDOWS.items(), ["midpoint", "opposite side"], [0.1, 0.3]):
        sig = signals(df, cfg, bar, win, target, buf)
        if sig.empty:
            continue
        c = {**cfg, "backtest": {**cfg["backtest"], "spread_usd": 0.30, "max_hold_bars": 8 * 60 // (bar.seconds // 60)},
             "strategy": {**cfg["strategy"], "partial_at_r": None, "breakeven_at_r": None}}
        t = simulate(sig, df, c)
        t = t[t["filled"]]
        r = t["r"].to_numpy()
        yrs = t.groupby(t["signal_time"].dt.year)["r"]
        pf = lambda x: round(x[x > 0].sum() / -x[x < 0].sum(), 2) if (x < 0).any() else None  # noqa: E731
        rows.append(dict(tf=tf, window=wname, target=target, sl_buffer=f"{buf} ATR", trades=len(r), per_week=round(len(r) / 197, 2),
                         win=round(100 * (r > 0).mean(), 1), avg_RR=round(sig["rr"].median(), 2), PF=pf(r), total_R=round(r.sum(), 1),
                         **{f"PF {y}": pf(g.to_numpy()) for y, g in yrs}))
    df = pd.DataFrame(rows)
    df.to_csv(resolve("research/asia_sweep_reclaim_results.csv"), index=False)
    pd.set_option("display.width", 230)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
