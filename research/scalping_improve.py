"""Can scalping be fixed?  python -m research.scalping_improve

The first scalping test lost mainly to costs (spread vs small M1 moves). Here the M1 setups from
research/scalping_test.py are generated once, then filtered by what should beat costs:
  * volatility vs cost: M1 ATR >= k x spread
  * active windows only: London open (02:00-05:00 NY) or New York open (08:00-11:00 NY)
  * double trend: H1 structure agrees with the M15 direction
  * bigger reward: 2R, 3R, or half at 1R + break-even with 2R
Choose on 2023-24, require 2025 to agree, report 2026 once.
"""
import itertools

import numpy as np
import pandas as pd

from goldbot.backtest.engine import simulate
from goldbot.config import load_config, resolve
from goldbot.data.store import resample
from goldbot.smc.structure import market_structure
from research.scalping_test import M1, context, generate, load_m1

SPREAD = 0.30
WINDOWS = {"London open": (120, 300), "NY open": (480, 660), "London+NY": None}
TARGETS = {"2R": dict(rr=2.0), "3R": dict(rr=3.0), "2R half+BE": dict(rr=2.0, partial_at_r=1.0, breakeven_at_r=1.0)}


def h1_trend(m1):
    h1 = resample(m1, "1h")
    right = pd.DataFrame({"t": h1.index + pd.Timedelta("1h"), "v": market_structure(h1, 2)["trend"].to_numpy()})
    return pd.merge_asof(pd.DataFrame({"t": m1.index + M1}), right, on="t", direction="backward")["v"].fillna(0).to_numpy()


def run(sig, m1, cfg, tgt):
    s = sig.copy()
    risk = (s["entry"] - s["sl"]).abs()
    d = np.where(s["direction"] == "BUY", 1, -1)
    s["rr"] = tgt["rr"]
    s["tp"] = (s["entry"] + d * tgt["rr"] * risk).round(2)
    c = {**cfg, "backtest": {**cfg["backtest"], "spread_usd": SPREAD, "max_hold_bars": 90},
         "strategy": {**cfg["strategy"], "partial_at_r": tgt.get("partial_at_r"), "partial_frac": 0.5,
                      "breakeven_at_r": tgt.get("breakeven_at_r")}}
    t = simulate(s, m1, c)
    return t[t["filled"]]


def stats(r):
    r = np.asarray(r, float)
    loss = -r[r < 0].sum()
    return dict(n=len(r), win=round(100 * (r > 0).mean(), 1) if len(r) else 0.0,
                PF=round(r[r > 0].sum() / loss, 2) if loss else 0.0, R=round(r.sum(), 1))


def main():
    cfg = load_config()
    m1 = load_m1()
    ctx = context(m1, cfg)
    h1 = h1_trend(m1)
    weeks = (m1.index[-1] - m1.index[0]).days / 7
    rows = []
    for concept in ("micro_ict", "bos_fvg"):
        base = generate(m1, ctx, concept, rr=2.0, max_day=10, cooldown=10)
        idx = m1.index.searchsorted(base["signal_time"] - M1)
        d = np.where(base["direction"] == "BUY", 1, -1)
        base["atr_x_spread"] = ctx["atr"][idx] / SPREAD
        base["minute"] = ctx["minute"][idx]
        base["h1_agree"] = h1[idx] == d
        print(f"{concept}: {len(base)} raw M1 setups", flush=True)
        for (wname, win), k, need_h1, (tname, tgt) in itertools.product(WINDOWS.items(), [0, 4, 6, 8], [False, True], TARGETS.items()):
            m = base["atr_x_spread"] >= k
            if win:
                m &= (base["minute"] >= win[0]) & (base["minute"] < win[1])
            if need_h1:
                m &= base["h1_agree"]
            sig = base[m]
            if len(sig) < 50:
                continue
            t = run(sig, m1, cfg, tgt)
            per = np.where(t["signal_time"] < "2025-01-01", "train", np.where(t["signal_time"] < "2026-01-01", "valid", "test"))
            st = {p: stats(t["r"][per == p]) for p in ("train", "valid", "test")}
            al = stats(t["r"])
            rows.append(dict(setup=concept, window=wname, atr_min=f"{k}x", h1=need_h1, target=tname,
                             per_week=round(al["n"] / weeks, 1), win=al["win"], PF=al["PF"], R=al["R"],
                             PF_2324=st["train"]["PF"], PF_2025=st["valid"]["PF"], PF_2026=st["test"]["PF"], win_2026=st["test"]["win"]))
    df = pd.DataFrame(rows)
    df.to_csv(resolve("research/scalping_improve_results.csv"), index=False)
    pd.set_option("display.width", 220)
    ok = df[(df["PF_2324"] > 1.1) & (df["PF_2025"] > 1.1)]
    print(f"\nTested {len(df)} improved scalping variants | PF>1.1 in 2023-24 AND 2025: {len(ok)} | of those PF>1 in 2026: {(ok['PF_2026'] > 1).sum()}")
    print("\nBest 12 by 2023-24 PF (chosen without looking at 2026):")
    print(df.sort_values("PF_2324", ascending=False).head(12).to_string(index=False))
    print("\nMedian PF by filter (all variants):")
    for col in ("window", "atr_min", "h1", "target"):
        print(df.groupby(col)[["PF_2324", "PF_2025", "PF_2026"]].median().round(2).to_string(), "\n")


if __name__ == "__main__":
    main()
