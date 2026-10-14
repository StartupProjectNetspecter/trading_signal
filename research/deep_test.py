"""Deep test: grid of strategy variants + walk-forward selection + spread stress.

    python -m research.deep_test
Writes research/deep_results.csv.
"""
import copy
import itertools
from multiprocessing import Pool

import numpy as np
import pandas as pd

from goldbot.backtest.engine import simulate
from goldbot.config import load_config, resolve
from goldbot.data.store import load_m5, load_smt
from goldbot.strategy.asian_sweep import generate_signals

SPLIT = pd.Timestamp("2025-07-01", tz="UTC")
MIN_TRADES = 30

GRID = {
    "liquidity_levels": [["asian"], ["asian", "pdh_pdl"], ["asian", "london"], ["asian", "pdh_pdl", "london"]],
    "smt_filter": [False, True],
    "kill_zones": [["london", "newyork"], ["newyork"]],
    "entry_model": ["ob", "fvg_then_ob"],
    "sl_buffer_atr": [0.2, 0.5],
    "management": ["2R", "3R", "1R", "2R+BE1", "2R+half1R+BE1"],
}
MANAGEMENT = {
    "1R": {"rr": 1.0},
    "2R": {"rr": 2.0},
    "3R": {"rr": 3.0},
    "2R+BE1": {"rr": 2.0, "breakeven_at_r": 1.0},
    "2R+half1R+BE1": {"rr": 2.0, "partial_at_r": 1.0, "partial_frac": 0.5, "breakeven_at_r": 1.0},
}

_M5 = _SMT = _CFG = None


def _init():
    global _M5, _SMT, _CFG
    _CFG = load_config()
    _M5 = load_m5(_CFG)
    _SMT = load_smt(_CFG)


def config_for(params):
    cfg = copy.deepcopy(_CFG)
    p = dict(params)
    cfg["strategy"].update(MANAGEMENT[p.pop("management")])
    cfg["strategy"].update(p)
    cfg["strategy"]["max_signals_per_day"] = 3
    return cfg


def name_of(p):
    lv = "+".join(x if x != "pdh_pdl" else "PDH/L" for x in p["liquidity_levels"])
    kz = "NY" if p["kill_zones"] == ["newyork"] else "LDN+NY"
    return f"{lv} | {'SMT' if p['smt_filter'] else '-'} | {kz} | {p['entry_model']} | SL{p['sl_buffer_atr']} | {p['management']}"


def metrics(r):
    r = np.asarray(r, float)
    if len(r) == 0:
        return dict(n=0, win=0.0, avgR=0.0, totR=0.0, PF=0.0)
    loss = -r[r < 0].sum()
    return dict(
        n=len(r),
        win=round(100 * (r > 0).mean(), 1),
        avgR=round(r.mean(), 3),
        totR=round(r.sum(), 1),
        PF=round(r[r > 0].sum() / loss, 2) if loss else 99.0,
    )


def run(params, spread=None):
    cfg = config_for(params)
    if spread is not None:
        cfg["backtest"]["spread_usd"] = spread
    sig = generate_signals(_M5, cfg, _SMT)
    if sig.empty:
        return params, pd.DataFrame(columns=["signal_time", "r"])
    t = simulate(sig, _M5, cfg)
    t = t[t["filled"]][["signal_time", "r"]].reset_index(drop=True)
    return params, t


def _run_stress(params):
    return run(params, spread=0.50)


def walk_forward(all_trades, names):
    """For each test year: pick the config with the best total R on all EARLIER data, then score it."""
    rows = []
    for year in (2025, 2026):
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        best, best_score = None, -np.inf
        for k, t in all_trades.items():
            past = t[t["signal_time"] < start]["r"]
            if len(past) >= MIN_TRADES and past.sum() > best_score:
                best, best_score = k, past.sum()
        test = all_trades[best]
        test = test[(test["signal_time"] >= start) & (test["signal_time"] < end)]["r"]
        rows.append({"test_year": year, "chosen_on_past": names[best], "past_totR": round(best_score, 1), **metrics(test)})
    return pd.DataFrame(rows)


def main():
    keys = list(GRID)
    combos = [dict(zip(keys, v)) for v in itertools.product(*GRID.values())]
    print(f"Testing {len(combos)} variants...")
    with Pool(initializer=_init) as pool:
        results = pool.map(run, combos)

    all_trades, names, rows = {}, {}, []
    for k, (p, t) in enumerate(results):
        all_trades[k], names[k] = t, name_of(p)
        is_r = t[t["signal_time"] < SPLIT]["r"]
        oos_r = t[t["signal_time"] >= SPLIT]["r"]
        years = t.groupby(t["signal_time"].dt.year)["r"].sum() if len(t) else pd.Series(dtype=float)
        row = {"id": k, "variant": names[k]}
        row.update({f"all_{a}": b for a, b in metrics(t["r"]).items()})
        row.update({f"IS_{a}": b for a, b in metrics(is_r).items()})
        row.update({f"OOS_{a}": b for a, b in metrics(oos_r).items()})
        row["years_positive"] = f"{int((years > 0).sum())}/{len(years)}"
        rows.append(row)
    df = pd.DataFrame(rows)

    # robust = enough trades and profitable in BOTH periods
    robust = df[(df["IS_n"] >= MIN_TRADES) & (df["OOS_n"] >= 10) & (df["IS_PF"] > 1) & (df["OOS_PF"] > 1)]
    top = robust.sort_values("IS_PF", ascending=False).head(10)

    # spread stress on the top candidates
    with Pool(initializer=_init) as pool:
        stressed = pool.map(_run_stress, [combos[i] for i in top["id"]])
    top = top.assign(PF_spread50=[metrics(t["r"])["PF"] for _, t in stressed])

    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 70)
    cols = ["variant", "all_n", "all_win", "all_totR", "all_PF", "IS_PF", "OOS_n", "OOS_win", "OOS_totR", "OOS_PF", "years_positive"]
    print(f"\nRobust variants (profitable in-sample AND out-of-sample): {len(robust)} of {len(df)}")
    print("\n== Top 10 robust, ranked by in-sample PF ==")
    print(top[cols + ["PF_spread50"]].to_string(index=False))

    win = robust[robust["all_n"] >= 50].sort_values("all_win", ascending=False).head(8)
    print("\n== Highest win rate among robust variants (50+ trades) ==")
    print(win[cols].to_string(index=False))

    print("\n== Walk-forward (choose on past only, then trade the next year) ==")
    print(walk_forward(all_trades, names).to_string(index=False))

    out = resolve("research/deep_results.csv")
    df.to_csv(out, index=False)
    print(f"\nAll {len(df)} results saved to {out}")


if __name__ == "__main__":
    main()
