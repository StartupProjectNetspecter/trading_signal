"""v2 research: daily-frequency models (Silver Bullet, Opening Range) on gold M5.

    python -m research.v2_daily_test
Goal: ~2+ trades/week with high win rate AND profit factor > 1 in both in-sample and out-of-sample.
Writes research/v2_daily_results.csv. Does not touch v1 (config.yaml / asian_sweep.py behaviour).
"""
import copy
import itertools
from multiprocessing import Pool

import pandas as pd

from goldbot.backtest.engine import simulate
from goldbot.config import load_config, resolve
from goldbot.data.store import load_m5
from goldbot.strategy.daily_models import generate_daily
from research.deep_test import metrics

SPLIT = pd.Timestamp("2025-07-01", tz="UTC")
MANAGEMENT = {
    "1R": {"rr": 1.0, "partial_at_r": None, "breakeven_at_r": None},
    "1.5R": {"rr": 1.5, "partial_at_r": None, "breakeven_at_r": None},
    "2R": {"rr": 2.0, "partial_at_r": None, "breakeven_at_r": None},
    "2R+half1R+BE1": {"rr": 2.0, "partial_at_r": 1.0, "partial_frac": 0.5, "breakeven_at_r": 1.0},
}
SB_WINDOWS = {
    "3 windows": [["03:00", "04:00"], ["10:00", "11:00"], ["14:00", "15:00"]],
    "10-11 NY": [["10:00", "11:00"]],
    "03-04 NY": [["03:00", "04:00"]],
}
ORB_RANGES = {"COMEX 08:20": ["08:20", "08:35"], "Stocks 09:30": ["09:30", "09:45"], "08:30-09:00": ["08:30", "09:00"]}


def variants():
    for w, sweep, disp, sl_at, buf, mg in itertools.product(SB_WINDOWS, [True, False], [0.5, 1.0], ["fvg", "leg"], [0.2, 0.5], MANAGEMENT):
        yield {
            "name": f"SB {w} | sweep={'Y' if sweep else 'N'} | disp{disp} | SL {sl_at}+{buf} | {mg}",
            "daily_models": ["silver_bullet"], "mg": mg, "sl_buffer_atr": buf,
            "silver_bullet": {"windows": SB_WINDOWS[w], "require_sweep": sweep, "min_displacement_atr": disp,
                              "min_fvg_atr": 0.1, "sl_at": sl_at, "pre_window_bars": 12, "expiry_after_window_bars": 6},
        }
    for r, entry, sl, max_r, buf, mg in itertools.product(ORB_RANGES, ["edge", "mid_retest"], ["mid", "opposite"], [3.0, 6.0], [0.2, 0.5], MANAGEMENT):
        yield {
            "name": f"ORB {r} | {entry} | SL {sl}+{buf} | range<{max_r}ATR | {mg}",
            "daily_models": ["opening_range"], "mg": mg, "sl_buffer_atr": buf,
            "opening_range": {"range": ORB_RANGES[r], "trade_until": "11:30", "entry": entry, "sl": sl,
                              "max_range_atr": max_r, "expiry_bars": 12},
        }


_M5 = _CFG = None


def _init():
    global _M5, _CFG
    _CFG = load_config()
    _M5 = load_m5(_CFG)


def run(v):
    cfg = copy.deepcopy(_CFG)
    st = cfg["strategy"]
    st.update(MANAGEMENT[v["mg"]])
    st.update({k: val for k, val in v.items() if k not in ("name", "mg")})
    st["entry_price"] = "ce"
    sig = generate_daily(_M5, cfg)
    if sig.empty:
        return v["name"], pd.DataFrame(columns=["signal_time", "r"])
    t = simulate(sig, _M5, cfg)
    return v["name"], t[t["filled"]][["signal_time", "r"]].reset_index(drop=True)


def main():
    vs = list(variants())
    print(f"Testing {len(vs)} v2 variants...")
    with Pool(initializer=_init) as pool:
        results = pool.map(run, vs)
    _init()
    weeks = (_M5.index[-1] - _M5.index[0]).days / 7
    rows, trades = [], {}
    for name, t in results:
        trades[name] = t
        row = {"variant": name, "per_week": round(len(t) / weeks, 2)}
        row.update({f"all_{a}": b for a, b in metrics(t["r"]).items()})
        row.update({f"IS_{a}": b for a, b in metrics(t[t["signal_time"] < SPLIT]["r"]).items()})
        row.update({f"OOS_{a}": b for a, b in metrics(t[t["signal_time"] >= SPLIT]["r"]).items()})
        yrs = t.groupby(t["signal_time"].dt.year)["r"].sum() if len(t) else pd.Series(dtype=float)
        row["years_pos"] = f"{int((yrs > 0).sum())}/{len(yrs)}"
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(resolve("research/v2_daily_results.csv"), index=False)

    pd.set_option("display.width", 260)
    pd.set_option("display.max_colwidth", 75)
    cols = ["variant", "per_week", "all_n", "all_win", "all_totR", "all_PF", "IS_PF", "OOS_n", "OOS_win", "OOS_PF", "years_pos"]
    robust = df[(df["IS_PF"] > 1) & (df["OOS_PF"] > 1) & (df["OOS_n"] >= 20)]
    print(f"\nProfitable in BOTH periods: {len(robust)} of {len(df)}")
    for lo, title in [(2.0, "2+ trades/week"), (1.0, "1+ trades/week")]:
        band = robust[robust["per_week"] >= lo]
        print(f"\n== {title}: {len(band)} robust variants (best by in-sample PF) ==")
        if len(band):
            print(band.sort_values("IS_PF", ascending=False).head(8)[cols].to_string(index=False))
    hw = robust[(robust["per_week"] >= 1.0) & (robust["all_win"] >= 55)]
    print(f"\n== High win rate (>=55%) and 1+/week: {len(hw)} ==")
    if len(hw):
        print(hw.sort_values("all_PF", ascending=False).head(8)[cols].to_string(index=False))

    print("\n== Walk-forward among 1+/week variants (choose on past, trade next year) ==")
    pool_names = df[df["per_week"] >= 1.0]["variant"].tolist()
    for year in (2025, 2026):
        start, end = pd.Timestamp(f"{year}-01-01", tz="UTC"), pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
        best = max(pool_names, key=lambda k: trades[k][trades[k]["signal_time"] < start]["r"].sum())
        tt = trades[best]
        test = tt[(tt["signal_time"] >= start) & (tt["signal_time"] < end)]["r"]
        print(f"  {year}: [{best}] past {tt[tt['signal_time'] < start]['r'].sum():+.1f}R -> {metrics(test)}")


if __name__ == "__main__":
    main()
