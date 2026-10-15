"""Can V3 (18:00 NY reopen buy) get a higher win rate?  python -m research.v3_improve

Management: add a take-profit and/or break-even instead of time-exit only.
Filters at signal time: H1 / daily structure trend up, previous session direction, volatility regime.
Choose on 2023-24, require 2025 to agree, report 2026.
"""
import itertools

import numpy as np
import pandas as pd

from goldbot.backtest.engine import simulate
from goldbot.config import load_config, resolve
from goldbot.data.store import load_m5, resample
from goldbot.smc.indicators import atr
from goldbot.smc.sessions import session_frame
from goldbot.smc.structure import market_structure
from goldbot.strategy.v3 import generate_v3

BAR = pd.Timedelta(minutes=5)
MANAGE = {
    "time only (now)": dict(tp=None, be=None),
    "TP 0.5R": dict(tp=0.5, be=None), "TP 1R": dict(tp=1.0, be=None), "TP 1.5R": dict(tp=1.5, be=None),
    "TP 1R + BE 0.5R": dict(tp=1.0, be=0.5), "BE 0.5R": dict(tp=None, be=0.5),
}


def trend(m5, tf):
    htf = resample(m5, tf)
    right = pd.DataFrame({"t": htf.index + pd.Timedelta(tf), "v": market_structure(htf, 2)["trend"].to_numpy()})
    return pd.merge_asof(pd.DataFrame({"t": m5.index + BAR}), right, on="t", direction="backward")["v"].fillna(0).to_numpy()


def stats(r):
    r = np.asarray(r, float)
    loss = -r[r < 0].sum()
    return dict(n=len(r), win=round(100 * (r > 0).mean(), 1) if len(r) else 0, PF=round(r[r > 0].sum() / loss, 2) if loss else 0, R=round(r.sum(), 1))


def main():
    cfg = load_config()
    m5 = load_m5(cfg)
    sig = generate_v3(m5, cfg)
    i = m5.index.searchsorted(sig["signal_time"] - BAR)
    h1, d1 = trend(m5, "1h"), trend(m5, "1D")
    sess = session_frame(m5.index, cfg)
    day = sess["session_day"].to_numpy()
    c = m5["close"].to_numpy()
    a = atr(m5, 14)
    regime = (a / a.rolling(288 * 5).mean()).to_numpy()
    # previous session: close of the bar before the reopen vs the previous session's first open
    prev_dir = []
    for k in i:
        prev = np.flatnonzero(day[:k] == day[k - 1])
        prev_dir.append(np.sign(c[k - 1] - m5["open"].iat[prev[0]]) if len(prev) else 0)
    feats = pd.DataFrame({"h1_up": h1[i] == 1, "d1_up": d1[i] == 1, "prev_down": np.array(prev_dir) < 0,
                          "prev_up": np.array(prev_dir) > 0, "vol_normal": (regime[i] > 0.7) & (regime[i] < 1.5)})
    filters = {"none (now)": np.ones(len(sig), bool), **{k: feats[k].to_numpy() for k in feats},
               "h1_up + d1_up": (feats.h1_up & feats.d1_up).to_numpy()}
    rows = []
    for (mname, mg), (fname, mask) in itertools.product(MANAGE.items(), filters.items()):
        s = sig[mask].copy()
        risk = s["entry"] - s["sl"]
        if mg["tp"]:
            s["tp"] = (s["entry"] + mg["tp"] * risk).round(2)
            s["rr"] = mg["tp"]
        c3 = {**cfg, "backtest": {**cfg["backtest"], "max_hold_bars": 72},
              "strategy": {**cfg["strategy"], "partial_at_r": None, "breakeven_at_r": mg["be"]}}
        t = simulate(s, m5, c3)
        t = t[t["filled"]]
        per = np.where(t["signal_time"] < "2025-01-01", "train", np.where(t["signal_time"] < "2026-01-01", "valid", "test"))
        st = {p: stats(t["r"][per == p]) for p in ("train", "valid", "test")}
        al = stats(t["r"])
        rows.append(dict(manage=mname, filter=fname, per_week=round(al["n"] / 197, 1), win=al["win"], PF=al["PF"], R=al["R"],
                         PF_2324=st["train"]["PF"], PF_2025=st["valid"]["PF"], PF_2026=st["test"]["PF"],
                         win_2324=st["train"]["win"], win_2025=st["valid"]["win"], win_2026=st["test"]["win"]))
    df = pd.DataFrame(rows)
    df.to_csv(resolve("research/v3_improve_results.csv"), index=False)
    pd.set_option("display.width", 230)
    base = df[(df.manage == "time only (now)") & (df["filter"] == "none (now)")].iloc[0]
    ok = df[(df.PF_2324 > base.PF_2324) & (df.PF_2025 > base.PF_2025) & (df.PF_2324 > 1) & (df.PF_2025 > 1)]
    print(f"Current V3: win {base.win}% PF {base.PF} ({base.per_week}/week)")
    print(f"\nVariants better than current in BOTH 2023-24 and 2025: {len(ok)} of {len(df)} -> their 2026:")
    print(ok.sort_values("PF_2324", ascending=False).head(12).to_string(index=False))
    print("\nHighest win rate variants (all):")
    print(df.sort_values("win", ascending=False).head(8).to_string(index=False))


if __name__ == "__main__":
    main()
