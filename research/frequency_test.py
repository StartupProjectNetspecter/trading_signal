"""Can we get 2-3 gold trades per week and keep the edge?

    python -m research.frequency_test
Tests the continuation model, market entries, sessions and order expiry. Writes research/frequency_results.csv.
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
from research.deep_test import metrics

SPLIT = pd.Timestamp("2025-07-01", tz="UTC")

GRID = {
    "models": [("reversal",), ("continuation",), ("reversal", "continuation")],
    "continuation_events": ["bos", "any"],
    "entry_price": ["ce", "market"],
    "kill_zones": [("newyork",), ("london", "newyork")],
    "entry_expiry_bars": [12, 24],
    "max_continuation_per_dir": [1, 2],
    "management": ["2R+half1R+BE1", "2R"],
}
MANAGEMENT = {
    "2R": {"rr": 2.0, "partial_at_r": None, "breakeven_at_r": None},
    "2R+half1R+BE1": {"rr": 2.0, "partial_at_r": 1.0, "partial_frac": 0.5, "breakeven_at_r": 1.0},
}

_M5 = _SMT = _CFG = None


def _init():
    global _M5, _SMT, _CFG
    _CFG = load_config()
    _M5 = load_m5(_CFG)
    _SMT = load_smt(_CFG)


def valid(p):
    # continuation-only knobs are meaningless without the continuation model; market ignores expiry
    if "continuation" not in p["models"] and (p["continuation_events"] != "bos" or p["max_continuation_per_dir"] != 1):
        return False
    if p["entry_price"] == "market" and p["entry_expiry_bars"] != 12:
        return False
    return True


def name_of(p):
    m = "+".join("REV" if x == "reversal" else "CONT" for x in p["models"])
    if "continuation" in p["models"]:
        m += f"({p['continuation_events']},{p['max_continuation_per_dir']}/dir)"
    kz = "NY" if p["kill_zones"] == ("newyork",) else "LDN+NY"
    entry = "market" if p["entry_price"] == "market" else f"limit {p['entry_expiry_bars'] * 5}m"
    return f"{m} | {kz} | {entry} | {p['management']}"


def run(p):
    cfg = copy.deepcopy(_CFG)
    q = dict(p)
    cfg["strategy"].update(MANAGEMENT[q.pop("management")])
    q["models"], q["kill_zones"] = list(q["models"]), list(q["kill_zones"])
    cfg["strategy"].update(q)
    cfg["strategy"]["max_signals_per_day"] = 4
    sig = generate_signals(_M5, cfg, _SMT)
    if sig.empty:
        return p, pd.DataFrame(columns=["signal_time", "r"])
    t = simulate(sig, _M5, cfg)
    return p, t[t["filled"]][["signal_time", "r"]].reset_index(drop=True)


def main():
    combos = [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())]
    combos = [p for p in combos if valid(p)]
    print(f"Testing {len(combos)} variants...")
    with Pool(initializer=_init) as pool:
        results = pool.map(run, combos)
    _init()
    weeks = (_M5.index[-1] - _M5.index[0]).days / 7

    rows, trades = [], {}
    for k, (p, t) in enumerate(results):
        trades[k] = t
        row = {"id": k, "variant": name_of(p), "per_week": round(len(t) / weeks, 2)}
        row.update({f"all_{a}": b for a, b in metrics(t["r"]).items()})
        row.update({f"IS_{a}": b for a, b in metrics(t[t["signal_time"] < SPLIT]["r"]).items()})
        row.update({f"OOS_{a}": b for a, b in metrics(t[t["signal_time"] >= SPLIT]["r"]).items()})
        yrs = t.groupby(t["signal_time"].dt.year)["r"].sum() if len(t) else pd.Series(dtype=float)
        row["years_pos"] = f"{int((yrs > 0).sum())}/{len(yrs)}"
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(resolve("research/frequency_results.csv"), index=False)

    pd.set_option("display.width", 260)
    pd.set_option("display.max_colwidth", 80)
    cols = ["variant", "per_week", "all_n", "all_win", "all_totR", "all_PF", "IS_PF", "OOS_n", "OOS_win", "OOS_PF", "years_pos"]
    for lo, hi, title in [(0, 0.75, "current frequency (<0.75/week)"), (0.75, 1.5, "0.75-1.5 trades/week"), (1.5, 99, "1.5+ trades/week (target)")]:
        band = df[(df["per_week"] >= lo) & (df["per_week"] < hi)]
        robust = band[(band["IS_PF"] > 1) & (band["OOS_PF"] > 1)]
        print(f"\n== {title}: {len(band)} variants, {len(robust)} profitable in both periods ==")
        if len(robust):
            print(robust.sort_values("IS_PF", ascending=False).head(6)[cols].to_string(index=False))

    # walk-forward restricted to high-frequency variants
    print("\n== Walk-forward among 1.5+/week variants (choose on past, trade next year) ==")
    hf = df[df["per_week"] >= 1.5]["id"].tolist()
    for year in (2025, 2026):
        start, end = pd.Timestamp(f"{year}-01-01", tz="UTC"), pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        best = max(hf, key=lambda k: trades[k][trades[k]["signal_time"] < start]["r"].sum(), default=None)
        if best is None:
            print("  no high-frequency variants")
            break
        test = trades[best][(trades[best]["signal_time"] >= start) & (trades[best]["signal_time"] < end)]["r"]
        past = trades[best][trades[best]["signal_time"] < start]["r"].sum()
        print(f"  {year}: chose [{df.loc[best, 'variant']}] (past {past:+.1f}R) -> {metrics(test)}")


if __name__ == "__main__":
    main()
