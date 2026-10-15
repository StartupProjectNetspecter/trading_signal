"""Three untested concept families that can trade every day.  python -m research.new_concepts

1. Time-of-day seasonality: buy/sell at NY hour h1, exit at hour h2 (same session day).
2. VWAP mean reversion: price stretched k ATR from the session VWAP -> fade back to VWAP.
3. ICT OTE: after a displacement leg of >= k ATR, limit entry at the 62-79% retracement.
Costs: spread $0.60 + slippage $0.10 per round trip (Codex base scenario).
Choose on TRAIN 2023-24, require VALIDATION 2025 to agree, report TEST 2026 once.
"""
import itertools

import numpy as np
import pandas as pd

from goldbot.backtest.engine import simulate
from goldbot.config import load_config
from goldbot.data.store import load_m5
from goldbot.smc.indicators import atr
from goldbot.smc.sessions import session_frame
from goldbot.strategy.asian_sweep import BAR

COST = 0.70


def period_of(t):
    t = pd.DatetimeIndex(t)
    return np.where(t < "2025-01-01", "train", np.where(t < "2026-01-01", "valid", "test"))


def summarize(r, per):
    out = {}
    for p in ("train", "valid", "test"):
        x = np.asarray(r)[per == p]
        loss = -x[x < 0].sum()
        out[p] = dict(n=len(x), win=100 * (x > 0).mean() if len(x) else 0, avg=x.mean() if len(x) else 0,
                      PF=x[x > 0].sum() / loss if loss else 0)
    return out


def seasonality(m5, cfg):
    sess = session_frame(m5.index, cfg)
    ny = m5.index.tz_convert("America/New_York")
    df = pd.DataFrame({"day": sess["session_day"].to_numpy(), "hour": ny.hour, "minute": ny.minute,
                       "open": m5["open"].to_numpy(), "atr": atr(m5, 14).to_numpy()}, index=m5.index)
    df = df[(df["minute"] == 0) & (df["day"].dt.weekday < 5)]
    px = df.pivot_table(index="day", columns="hour", values="open", aggfunc="first")
    a = df.pivot_table(index="day", columns="hour", values="atr", aggfunc="first")
    order = list(range(18, 24)) + list(range(0, 17))  # session day runs 18:00 -> 17:00 NY
    rows = []
    for i, h1 in enumerate(order):
        for h2 in order[i + 1 : i + 13]:  # hold 1..12 hours
            move = (px[h2] - px[h1]).dropna()
            risk = a[h1].reindex(move.index) * 2  # express result in R of a 2-ATR stop
            per = period_of(pd.DatetimeIndex(move.index).tz_localize("UTC"))
            for d in (1, -1):
                r = ((move * d) - COST) / risk
                s = summarize(r.to_numpy(), per)
                rows.append(dict(rule=f"{'BUY' if d == 1 else 'SELL'} {h1:02d}:00 -> exit {h2:02d}:00 NY", **{f"{p}_{k}": v for p in s for k, v in s[p].items()}))
    return pd.DataFrame(rows)


def vwap_reversion(m5, cfg):
    sess = session_frame(m5.index, cfg)
    day = sess["session_day"].to_numpy()
    tp = (m5["high"] + m5["low"] + m5["close"]) / 3
    vol = m5["volume"].clip(lower=1)
    vwap = (tp * vol).groupby(day).cumsum() / vol.groupby(day).cumsum()
    a = atr(m5, 14)
    stretch = ((m5["close"] - vwap) / a).to_numpy()
    c, vw, av = m5["close"].to_numpy(), vwap.to_numpy(), a.to_numpy()
    ny_hour = sess["ny_hour"].to_numpy()
    news = sess["news_block"].to_numpy()
    rows, trades_by = [], {}
    for k, hours, stop_k in itertools.product([2.0, 3.0, 4.0], [(2, 11), (7, 11), (2, 15)], [1.0, 2.0]):
        sigs, last_day = [], None
        for i in np.flatnonzero((np.abs(stretch) >= k) & (ny_hour >= hours[0]) & (ny_hour < hours[1]) & ~news):
            if day[i] == last_day or np.isnan(av[i]):
                continue
            d = -1 if stretch[i] > 0 else 1  # fade the stretch
            entry, risk = c[i], stop_k * av[i]
            target = vw[i]
            rr = (target - entry) * d / risk
            if rr < 0.5:
                continue
            sigs.append({"signal_time": m5.index[i] + BAR, "expiry_time": m5.index[i] + 2 * BAR, "direction": "BUY" if d == 1 else "SELL",
                         "entry": entry, "sl": entry - d * risk, "tp": target, "rr": rr, "order": "market"})
            last_day = day[i]
        name = f"VWAP fade {k} ATR | NY {hours[0]:02d}-{hours[1]:02d}h | SL {stop_k} ATR"
        rows.append((name, pd.DataFrame(sigs)))
    return rows


def ote(m5, cfg):
    sess = session_frame(m5.index, cfg)
    o, h, l, c = (m5[x].to_numpy() for x in ("open", "high", "low", "close"))
    a = atr(m5, 14).to_numpy()
    ny_hour = sess["ny_hour"].to_numpy()
    news = sess["news_block"].to_numpy()
    rows = []
    for k, look, hours in itertools.product([3.0, 4.0, 5.0], [6, 12], [(2, 11), (7, 11)]):
        sigs, last = [], -100
        for i in range(look, len(m5)):
            if not (hours[0] <= ny_hour[i] < hours[1]) or news[i] or np.isnan(a[i]) or i - last < 24:
                continue
            lo, hi = l[i - look + 1 : i + 1].min(), h[i - look + 1 : i + 1].max()
            if hi - lo < k * a[i]:
                continue
            up = np.argmax(h[i - look + 1 : i + 1]) > np.argmin(l[i - look + 1 : i + 1])  # low came first -> up leg
            if up and c[i] < hi - 0.25 * (hi - lo):
                continue  # leg must close near its extreme (displacement just happened)
            if not up and c[i] > lo + 0.25 * (hi - lo):
                continue
            d = 1 if up else -1
            entry = hi - 0.705 * (hi - lo) if up else lo + 0.705 * (hi - lo)  # OTE sweet spot
            sl = lo - 0.2 * a[i] if up else hi + 0.2 * a[i]
            risk = (entry - sl) * d
            tp = hi if up else lo  # back to the leg extreme
            sigs.append({"signal_time": m5.index[i] + BAR, "expiry_time": m5.index[i] + 13 * BAR, "direction": "BUY" if d == 1 else "SELL",
                         "entry": entry, "sl": sl, "tp": tp, "rr": (tp - entry) * d / risk, "order": "limit"})
            last = i
        rows.append((f"OTE leg>={k} ATR in {look} bars | NY {hours[0]:02d}-{hours[1]:02d}h", pd.DataFrame(sigs)))
    return rows


def run_sim(variants, m5, cfg):
    cfg = {**cfg, "backtest": {**cfg["backtest"], "spread_usd": 0.60},
           "strategy": {**cfg["strategy"], "partial_at_r": None, "breakeven_at_r": None}}
    out = []
    for name, sig in variants:
        if sig.empty:
            continue
        t = simulate(sig, m5, cfg)
        t = t[t["filled"]]
        s = summarize(t["r"].to_numpy(), period_of(t["signal_time"]))
        out.append(dict(rule=name, **{f"{p}_{k}": v for p in s for k, v in s[p].items()}))
    return pd.DataFrame(out)


def report(title, df, weeks=197):
    good = df[(df["train_PF"] > 1.1) & (df["valid_PF"] > 1.1) & (df["train_n"] >= 50)]
    held = good[good["test_PF"] > 1.0]
    print(f"\n== {title}: {len(df)} variants | PF>1.1 in train AND 2025: {len(good)} | of those profitable in 2026: {len(held)}")
    cols = ["rule", "train_n", "train_win", "train_PF", "valid_win", "valid_PF", "test_n", "test_win", "test_PF"]
    if len(good):
        g = good.sort_values("train_PF", ascending=False).head(10)[cols].copy()
        g["per_week"] = ((g["train_n"] + g["test_n"]) / (weeks * 0.6)).round(2)
        print(g.round(2).to_string(index=False))


def main():
    cfg = load_config()
    m5 = load_m5(cfg)
    pd.set_option("display.width", 230)
    report("1. Time-of-day seasonality", seasonality(m5, cfg))
    report("2. VWAP mean reversion", run_sim(vwap_reversion(m5, cfg), m5, cfg))
    report("3. ICT OTE retracement", run_sim(ote(m5, cfg), m5, cfg))


if __name__ == "__main__":
    main()
