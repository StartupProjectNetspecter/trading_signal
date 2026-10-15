"""Pasted 'NY Breakout & Retest' rules, tested exactly (with a realistic stop).  python -m research.orb_retest_pasted

Range 08:30-09:00 NY (or 09:30-09:45). H1 EMA50 trend filter (or M5 EMA200). Break = M5 close outside the
range in trend direction. Retest = a later M5 candle touches the broken line and closes back outside -> enter at
its close. SL beyond the retest wick + buffer. TP 2R. No new setups after 12:00 NY (23:00 Cambodia).
"""
import itertools

import numpy as np
import pandas as pd

from goldbot.backtest.engine import simulate
from goldbot.config import load_config, resolve
from goldbot.data.store import load_m5, resample
from goldbot.smc.indicators import atr
from goldbot.smc.sessions import news_mask

BAR = pd.Timedelta(minutes=5)


def h1_ema_side(m5, span):
    h1 = resample(m5, "1h")
    side = np.sign(h1["close"] - h1["close"].ewm(span=span, adjust=False).mean())
    right = pd.DataFrame({"t": h1.index + pd.Timedelta("1h"), "v": side.to_numpy()})
    return pd.merge_asof(pd.DataFrame({"t": m5.index + BAR}), right, on="t", direction="backward")["v"].fillna(0).to_numpy()


def signals(m5, cfg, rng_start, rng_len, trend, sl_buf_atr, rr, vol_filter):
    ny = m5.index.tz_convert("America/New_York")
    minute = (ny.hour * 60 + ny.minute).to_numpy()
    day = ny.tz_localize(None).normalize().to_numpy()
    o, h, l, c, v = (m5[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    a = atr(m5, 14).to_numpy()
    news = news_mask(m5.index, cfg)
    tr = h1_ema_side(m5, 50) if trend == "H1 EMA50" else np.sign(m5["close"] - m5["close"].ewm(span=200, adjust=False).mean()).to_numpy()
    vol_avg = pd.Series(v).rolling(20).mean().shift(1).to_numpy()
    out = []
    for dval in np.unique(day[(minute >= rng_start) & (minute < rng_start + rng_len)]):
        if pd.Timestamp(dval).weekday() >= 5:
            continue
        r = np.flatnonzero((day == dval) & (minute >= rng_start) & (minute < rng_start + rng_len))
        if len(r) != rng_len // 5:
            continue
        hi, lo = h[r].max(), l[r].min()
        t = np.flatnonzero((day == dval) & (np.arange(len(m5)) > r[-1]) & (minute < 720))
        broke = 0
        for i in t:
            if news[i]:
                continue
            if not broke:
                d = 1 if c[i] > hi else -1 if c[i] < lo else 0
                if d == 0:
                    continue
                if tr[i] != d or (vol_filter and not v[i] > 1.5 * vol_avg[i]):
                    break  # first breakout against the filter: no trade today
                broke, line = d, (hi if d == 1 else lo)
                continue
            d = broke
            touched = l[i] <= line if d == 1 else h[i] >= line
            closed_out = c[i] > line if d == 1 else c[i] < line
            if touched and closed_out:
                sl = (l[i] - sl_buf_atr * a[i]) if d == 1 else (h[i] + sl_buf_atr * a[i])
                risk = (c[i] - sl) * d
                if risk >= 1.0:
                    out.append({"signal_time": m5.index[i] + BAR, "expiry_time": m5.index[i] + 2 * BAR, "direction": "BUY" if d == 1 else "SELL",
                                "entry": c[i], "sl": sl, "tp": c[i] + d * rr * risk, "rr": rr, "order": "market"})
                break
            if (c[i] - line) * d < 0 and not touched:
                break
    return pd.DataFrame(out)


def main():
    cfg = load_config()
    m5 = load_m5(cfg)
    rows = []
    for (rs, rl), trend, buf, rr, volf in itertools.product([(510, 30), (570, 15)], ["H1 EMA50", "M5 EMA200"], [0.1, 0.3], [1.5, 2.0], [False, True]):
        sig = signals(m5, cfg, rs, rl, trend, buf, rr, volf)
        if sig.empty:
            continue
        c = {**cfg, "backtest": {**cfg["backtest"], "spread_usd": 0.30, "max_hold_bars": 96},
             "strategy": {**cfg["strategy"], "partial_at_r": None, "breakeven_at_r": None}}
        t = simulate(sig, m5, c)
        t = t[t["filled"]]
        r = t["r"].to_numpy()
        pf = lambda x: round(x[x > 0].sum() / -x[x < 0].sum(), 2) if (x < 0).any() else None  # noqa: E731
        yrs = {y: pf(g.to_numpy()) for y, g in t.groupby(t["signal_time"].dt.year)["r"]}
        rows.append(dict(range=f"{rs // 60:02d}:{rs % 60:02d}+{rl}m", trend=trend, sl_buf=buf, rr=rr, volume=volf, trades=len(r),
                         per_week=round(len(r) / 197, 2), win=round(100 * (r > 0).mean(), 1), PF=pf(r), R=round(r.sum(), 1),
                         **{f"PF {y}": p for y, p in yrs.items()}))
    df = pd.DataFrame(rows)
    df.to_csv(resolve("research/orb_retest_pasted_results.csv"), index=False)
    pd.set_option("display.width", 230)
    print(df.sort_values("PF", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
