"""v2 research: H1 -> M15 -> M5 confluence. Which factor combinations give many trades AND an edge?

    python -m research.mtf_test
Train (choose): 2023-01 .. 2025-06.  Validate (judge): 2025-07 .. now.  Plus yearly walk-forward.
Writes research/mtf_results.csv.
"""
import itertools
from multiprocessing import Pool

import numpy as np
import pandas as pd

from goldbot.backtest.engine import simulate
from goldbot.config import load_config, resolve
from goldbot.data.store import load_m5, load_smt
from goldbot.strategy import mtf_confluence as mc

SPLIT = pd.Timestamp("2025-07-01", tz="UTC")
MTF = dict(m5_swing_n=2, m15_swing_n=2, zone_max_age_bars=288, zone_break_atr=0.5,
           max_bars_tap_to_choch=24, sl_buffer_atr=0.3, displacement_atr=0.7)
TARGETS = {
    "1R": dict(rr=1.0), "1.5R": dict(rr=1.5), "2R": dict(rr=2.0), "3R": dict(rr=3.0),
    "2R+half1R+BE1": dict(rr=2.0, partial_at_r=1.0, partial_frac=0.5, breakeven_at_r=1.0),
    "H1 liquidity": dict(rr=None, tp_mode="h1"),
}
ENTRIES = ["market", "limit"]

_M5 = _CFG = _CANDS = None


def _init():
    global _M5, _CFG, _CANDS
    _CFG = load_config()
    _CFG["strategy"]["mtf"] = MTF
    _M5 = load_m5(_CFG)
    _CANDS = mc.candidates(_M5, _CFG, load_smt(_CFG))


def simulate_all(args):
    entry, tname = args
    t = TARGETS[tname]
    cfg = {**_CFG, "strategy": {**_CFG["strategy"], "partial_at_r": t.get("partial_at_r"),
                                "partial_frac": t.get("partial_frac", 0.5), "breakeven_at_r": t.get("breakeven_at_r")}}
    sig = mc.to_signals(_CANDS, entry, t["rr"], t.get("tp_mode", "rr"), min_rr=1.0)
    tr = simulate(sig, _M5, cfg)
    return entry, tname, tr[tr["filled"]].reset_index(drop=True)


def stats(r):
    r = np.asarray(r, float)
    if len(r) == 0:
        return 0, 0.0, 0.0, 0.0
    loss = -r[r < 0].sum()
    return len(r), 100 * (r > 0).mean(), r.sum(), (r[r > 0].sum() / loss if loss else 99.0)


def filters():
    req = lambda f: [None, f]  # noqa: E731  (None = not required)
    for tr, disc, zone, sw, kz, disp, smt in itertools.product(
        req("h1_trend"), req("h1_discount"), [None, "m15_ob", "m15_fvg"], req("sweep"), req("kill_zone"),
        req("displacement"), req("smt")
    ):
        yield [f for f in (tr, disc, zone, sw, kz, disp, smt) if f]


def main():
    with Pool(initializer=_init) as pool:
        sims = pool.map(simulate_all, list(itertools.product(ENTRIES, TARGETS)))
    _init()
    weeks_tr = (SPLIT - _M5.index[0]).days / 7
    weeks_va = (_M5.index[-1] - SPLIT).days / 7
    rows, store = [], {}
    for entry, tname, tr in sims:
        is_tr = tr["signal_time"] < SPLIT
        years = tr["signal_time"].dt.year
        for req in filters():
            m = np.ones(len(tr), bool)
            for f in req:
                m &= tr[f].to_numpy()
            key = f"{entry} | {tname} | " + (" + ".join(req) if req else "no filter")
            r = tr["r"].to_numpy()
            n1, w1, t1, pf1 = stats(r[m & is_tr])
            n2, w2, t2, pf2 = stats(r[m & ~is_tr])
            yr = pd.Series(r[m]).groupby(years[m].to_numpy()).sum()
            store[key] = (tr.loc[m, ["signal_time", "r"]])
            rows.append(dict(variant=key, factors=len(req), train_per_week=round(n1 / weeks_tr, 2), train_win=round(w1, 1),
                             train_PF=round(pf1, 2), train_R=round(t1, 1), valid_per_week=round(n2 / weeks_va, 2),
                             valid_win=round(w2, 1), valid_PF=round(pf2, 2), valid_R=round(t2, 1),
                             years_pos=f"{int((yr > 0).sum())}/{len(yr)}"))
    df = pd.DataFrame(rows)
    df.to_csv(resolve("research/mtf_results.csv"), index=False)
    print(f"Tested {len(df)} variants ({len(ENTRIES)} entries x {len(TARGETS)} targets x {len(df) // 12} factor filters)")

    pd.set_option("display.width", 260)
    pd.set_option("display.max_colwidth", 95)
    cols = ["variant", "train_per_week", "train_win", "train_PF", "valid_per_week", "valid_win", "valid_PF", "valid_R", "years_pos"]
    for min_pw in (2.0, 1.0):
        pool_ = df[df["train_per_week"] >= min_pw]
        print(f"\n== Chosen on TRAIN only, {min_pw}+ trades/week: top 8 by train PF, then judged on VALIDATION ==")
        print(pool_.sort_values("train_PF", ascending=False).head(8)[cols].to_string(index=False))
        ok = pool_[(pool_["train_PF"] > 1.2) & (pool_["valid_PF"] > 1.2)]
        print(f"   variants with PF > 1.2 in BOTH periods at {min_pw}+/week: {len(ok)} of {len(pool_)}")
    hw = df[(df["train_per_week"] >= 1.0) & (df["train_win"] >= 60) & (df["valid_win"] >= 60) & (df["train_PF"] > 1) & (df["valid_PF"] > 1)]
    print(f"\n== Win rate >= 60% in both periods, PF > 1 in both, 1+/week: {len(hw)} ==")
    if len(hw):
        print(hw.sort_values("valid_PF", ascending=False).head(8)[cols].to_string(index=False))

    print("\n== Walk-forward: pick best TRAIN PF among 2+/week variants using only past data ==")
    for year in (2025, 2026):
        start, end = pd.Timestamp(f"{year}-01-01", tz="UTC"), pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        weeks_past = (start - _M5.index[0]).days / 7
        best, best_pf = None, -1
        for k, t in store.items():
            past = t[t["signal_time"] < start]["r"].to_numpy()
            n, _, _, pf = stats(past)
            if n / weeks_past >= 2 and pf > best_pf:
                best, best_pf = k, pf
        test = store[best]
        test = test[(test["signal_time"] >= start) & (test["signal_time"] < end)]["r"].to_numpy()
        n, w, tot, pf = stats(test)
        print(f"  {year}: [{best}] past PF {best_pf:.2f} -> {n} trades, win {w:.1f}%, {tot:+.1f}R, PF {pf:.2f}")


if __name__ == "__main__":
    main()
