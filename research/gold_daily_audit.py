"""Deep frequency/accuracy audit: python -m research.gold_daily_audit.

Isolated research; never edits config.yaml or sends Telegram alerts.
"""
import copy
import hashlib
import itertools
import json
import math

import numpy as np
import pandas as pd
import yaml

from goldbot.config import ROOT, load_config
from goldbot.data.store import load_m5
from goldbot.backtest.engine import simulate
from goldbot.strategy.asian_sweep import generate_signals
from research.causal_gold import CONCEPTS, BAR, features, proposals, generate, execute

OUT = ROOT / "reports" / "daily_audit"
BOUNDARIES = [pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")]


def metrics(trades, f, start=None, end=None):
    times = pd.DatetimeIndex(f.close_time)
    mask = (times >= start if start is not None else np.ones(len(f), bool)) & (
        times < end if end is not None else np.ones(len(f), bool))
    days = pd.DatetimeIndex(f.loc[mask & (f.weekday < 5), "day"].unique()).sort_values()
    signals = trades.copy()
    if len(signals) and start is not None:
        signals = signals[signals.signal_time >= start]
    if len(signals) and end is not None:
        signals = signals[signals.signal_time < end]
    signal_days = (set(pd.DatetimeIndex(signals.signal_time).tz_convert("America/New_York").tz_localize(None).normalize())
                   if len(signals) else set())
    t = trades.copy()
    if len(t):
        if start is not None:
            t = t[t.signal_time >= start]
        if end is not None:
            # Exclude unresolved boundary positions, rather than leaking their later outcome.
            t = t[(t.signal_time < end) & (~t.filled | (t.exit_time < end))]
        t = t[t.filled & (t.exit_time <= times[-1])].sort_values("exit_time")
    r = t.r.to_numpy() if len(t) else np.array([])
    n, wins = len(r), int((r > 0).sum())
    if n:
        z, p = 1.96, wins/n
        den = 1+z*z/n
        ctr = (p+z*z/(2*n))/den
        delta = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
        loss = -r[r < 0].sum()
        cum = np.r_[0, np.cumsum(r)]
        dd = (np.maximum.accumulate(cum)-cum).max()
        filled_days = pd.DatetimeIndex(t.fill_time).tz_convert("America/New_York").tz_localize(None).normalize()
        active = set(filled_days)
        longest, streak = 0, 0
        for day in days:
            streak = 0 if day in active else streak+1
            longest = max(longest, streak)
    else:
        ctr = delta = dd = 0
        active, longest = set(), len(days)
        loss = 0
    return {
        "n": n, "signals": len(signals),
        "signals_per_week": 5*len(signals)/len(days) if len(days) else 0,
        "signal_days_pct": 100*len(signal_days & set(days))/len(days) if len(days) else 0,
        "win_pct": 100*wins/n if n else 0,
        "win_ci_low_pct": 100*max(0, ctr-delta), "win_ci_high_pct": 100*min(1, ctr+delta),
        "avg_R": float(r.mean()) if n else 0, "total_R": float(r.sum()),
        "PF": float(r[r > 0].sum()/loss) if loss else (float("inf") if n else 0),
        "max_dd_R": float(dd), "filled_days_pct": 100*len(active & set(days))/len(days) if len(days) else 0,
        "fills_per_week": 5*n/len(days) if len(days) else 0,
        "max_no_fill_trading_days": longest, "available_trading_days": len(days),
    }


def summarize(t, f):
    row = {}
    for name, start, end in [("train", None, BOUNDARIES[0]),
                             ("validation", BOUNDARIES[0], BOUNDARIES[1]),
                             ("test", BOUNDARIES[1], None), ("all", None, None)]:
        row.update({f"{name}_{key}": val for key, val in metrics(t, f, start, end).items()})
    return row


def variants():
    for concept in CONCEPTS:
        ns = [2, 3] if concept in ["hhhl_pullback", "bos"] else [2]
        for n, bias, session, buffer, rr in itertools.product(
                ns, ["none", "h1_bos", "h1_hhhl"], ["ny", "london_ny"], [0.2, 0.5], [0.75, 1.0, 1.5]):
            yield dict(concept=concept, n=n, bias=bias, session=session, buffer=buffer, rr=rr)


def main(resume=False):
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    m5 = load_m5(cfg)
    print("Computing causal features...", flush=True)
    f = features(m5, cfg)
    # Exact feature export: confirmation timestamp plus the actual pivot values.
    evidence = f.loc[f.s2_high_confirmed | f.s2_low_confirmed,
                     ["close_time", "s2_high", "s2_previous_high", "s2_high_label",
                      "s2_high_pivot_index", "s2_high_confirmed", "s2_low", "s2_previous_low",
                      "s2_low_label", "s2_low_pivot_index", "s2_low_confirmed", "s2_trend"]].copy()
    for side in ["high", "low"]:
        positions = evidence[f"s2_{side}_pivot_index"].to_numpy(int)
        evidence[f"{side}_pivot_time"] = [m5.index[i] if i >= 0 else pd.NaT for i in positions]
    evidence.to_csv(OUT / "confirmed_structure_values.csv", index=False)
    metadata = {"bars": len(m5), "start": str(m5.index[0]), "end": str(m5.index[-1]),
                "data_sha256": hashlib.sha256((ROOT / "data" / "mt5_XAUUSD_M5.csv").read_bytes()).hexdigest(),
                "config": cfg, "costs": {"spread": 0.3, "slippage_per_market_or_stop_exit": 0.05,
                                         "round_trip_commission_usd_per_oz": 0.0},
                "splits": [str(t) for t in BOUNDARIES],
                "data_quality": {"duplicates": int(m5.index.duplicated().sum()),
                                  "sorted": bool(m5.index.is_monotonic_increasing),
                                  "missing": int(m5.isna().sum().sum())}}
    (OUT / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    cfg_baseline = copy.deepcopy(cfg)
    baseline_signals = generate_signals(m5, cfg_baseline)
    baseline = simulate(baseline_signals, m5, cfg_baseline)
    baseline.to_csv(OUT / "baseline_trades.csv", index=False)
    (OUT / "baseline_metrics.json").write_text(json.dumps(summarize(baseline, f), indent=2), encoding="utf-8")
    vs = list(variants())
    rows, raw_cache, params_by_id = [], {}, {k: p for k, p in enumerate(vs)}
    if resume and (OUT / "variants.csv").exists():
        previous = pd.read_csv(OUT / "variants.csv")
        # Recompute opening-range rows after the datetime-unit portability correction.
        previous = previous[previous.concept != "opening_range"]
        rows = previous.to_dict("records")
    completed = {int(row["id"]) for row in rows}
    def raw_for(p):
        key = (p["concept"], p["n"])
        if key not in raw_cache:
            raw_cache[key] = proposals(f, *key)
        return raw_cache[key]
    for k, p in enumerate(vs):
        if k in completed:
            continue
        sig = generate(f, raw_for(p), p)
        t = execute(sig, m5)
        row = {"id": k, **p, **summarize(t, f)}
        rows.append(row)
        params_by_id[k] = p
        if (k+1) % 12 == 0:
            print(f"{k+1}/{len(vs)} {p['concept']}: {row['all_n']} fills, "
                  f"{row['all_win_pct']:.1f}% wins, {row['all_fills_per_week']:.2f}/week", flush=True)
            pd.DataFrame(rows).to_csv(OUT / "variants.csv", index=False)
    df = pd.DataFrame(rows).sort_values("id")
    # Full frequency criteria use PAST periods only, never 2026 outcomes/coverage.
    df["enough"] = (df.train_n >= 100) & (df.validation_n >= 50)
    df["frequency"] = (df.train_filled_days_pct >= 50) & (df.validation_filled_days_pct >= 50)
    df["profitable"] = (df.train_avg_R > 0) & (df.validation_avg_R > 0)
    df["high_win"] = (df.train_win_pct >= 55) & (df.validation_win_pct >= 55)
    df["score"] = df[["train_avg_R", "validation_avg_R"]].min(axis=1)
    df.to_csv(OUT / "variants.csv", index=False)
    qualified = df[df.enough & df.frequency & df.profitable & df.high_win].sort_values("score", ascending=False)
    qualified.to_csv(OUT / "qualified.csv", index=False)
    print(f"QUALIFIED {len(qualified)} / {len(df)}", flush=True)
    selected = {}
    for label, mask in [("target", df.enough & df.frequency & df.profitable & df.high_win),
                        ("frequent", df.enough & df.frequency),
                        ("profitable", df.enough & df.profitable),
                        ("high_win", df.enough & df.high_win)]:
        ranked = df[mask].sort_values(["score", "validation_n"], ascending=False)
        if len(ranked):
            selected[label] = int(ranked.iloc[0].id)
    stress, years = [], []
    for k in sorted(set(selected.values())):
        p = params_by_id[k]
        sig = generate(f, raw_for(p), p)
        sig.to_csv(OUT / f"candidate_{k}_signals.csv", index=False)
        (OUT / f"candidate_{k}.yaml").write_text(
            "# RESEARCH ONLY: requires research.causal_gold; not a live-bot config.\n"+
            yaml.safe_dump(p, sort_keys=False), encoding="utf-8")
        for spread, slippage, commission in [(0.3, 0.05, 0), (0.6, 0.1, 0), (0.9, 0.15, 0), (0.3, 0.05, 0.1)]:
            t = execute(sig, m5, spread, slippage, commission)
            stress.append(dict(id=k, spread=spread, slippage=slippage, commission=commission, **summarize(t, f)))
            if spread == 0.3 and commission == 0:
                t.to_csv(OUT / f"candidate_{k}_trades.csv", index=False)
                for year in [2023, 2024, 2025, 2026]:
                    start, end = pd.Timestamp(f"{year}-01-01", tz="UTC"), pd.Timestamp(f"{year+1}-01-01", tz="UTC")
                    years.append(dict(id=k, year=year, **metrics(t, f, start, end)))
    pd.DataFrame(stress).to_csv(OUT / "stress.csv", index=False)
    pd.DataFrame(years).to_csv(OUT / "years.csv", index=False)
    (OUT / "selected.json").write_text(json.dumps(selected, indent=2), encoding="utf-8")
    # Rolling year selection: choose only on completed past outcomes and past frequency.
    wf = []
    for year in [2025, 2026]:
        eligible = df[(df.train_n >= 100) & (df.train_filled_days_pct >= 50)] if year == 2025 else df[df.enough & df.frequency]
        rank = "train_avg_R" if year == 2025 else "score"
        if len(eligible):
            chosen = int(eligible.sort_values(rank, ascending=False).iloc[0].id)
            p = params_by_id[chosen]
            sig = generate(f, raw_for(p), p)
            t = execute(sig, m5)
            wf_params = {("swing_n" if key == "n" else key): value for key, value in p.items()}
            wf.append(dict(year=year, id=chosen, **wf_params, **metrics(t, f,
                           pd.Timestamp(f"{year}-01-01", tz="UTC"), pd.Timestamp(f"{year+1}-01-01", tz="UTC"))))
    pd.DataFrame(wf).to_csv(OUT / "walk_forward.csv", index=False)
    print("SELECTION", selected, flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true", help="Reuse completed rows on the same data/config")
    main(parser.parse_args().resume)
