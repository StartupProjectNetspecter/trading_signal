"""Past-selected higher-RR, corrected-calendar, and combined-concept checks."""
import copy
import json

import numpy as np
import pandas as pd

from goldbot.config import ROOT, load_config
from goldbot.data.store import load_m5
from research.causal_gold import features, proposals, generate, execute
from research.gold_daily_audit import OUT, summarize


def main():
    cfg = load_config()
    events = pd.read_csv(ROOT / cfg["news"]["events_file"])
    events = pd.concat([events, pd.DataFrame([{"datetime_utc": "2023-01-12 13:30", "event": "CPI"}])])
    events["datetime_utc"] = pd.to_datetime(events.datetime_utc, utc=True)
    events = events.drop_duplicates(["datetime_utc", "event"]).sort_values("datetime_utc")
    events.to_csv(OUT / "news_events_checked.csv", index=False, date_format="%Y-%m-%d %H:%M")
    # Only the confirmed omission is corrected. This is not a complete source audit.
    cfg["news"]["events_file"] = str(OUT / "news_events_checked.csv")
    m5 = load_m5(cfg)
    f = features(m5, cfg)
    df = pd.read_csv(OUT / "variants.csv")
    enough = df[(df.train_n >= 100) & (df.validation_n >= 50)]
    selected = enough.sort_values("score", ascending=False).groupby("concept", sort=False).head(1)
    rows, signals, selected_configs = [], {}, {}
    for record in selected.to_dict("records"):
        p = {key: record[key] for key in ["concept", "n", "bias", "session", "buffer", "rr"]}
        p["n"] = int(p["n"])
        raw = proposals(f, p["concept"], p["n"])
        for rr in [p["rr"], 2.0, 3.0]:
            q = dict(p, rr=rr)
            diag = {}
            sig = generate(f, raw, q, diag)
            t = execute(sig, m5)
            name = f"{p['concept']}_rr{rr}"
            rows.append(dict(name=name, **q, **summarize(t, f)))
            if rr == p["rr"]:
                signals[p["concept"]] = sig
                selected_configs[p["concept"]] = q
                t.to_csv(OUT / f"concept_{p['concept']}_trades.csv", index=False)
                sig.to_csv(OUT / f"concept_{p['concept']}_values.csv", index=False)
                (OUT / f"concept_{p['concept']}_funnel.json").write_text(json.dumps(diag, indent=2), encoding="utf-8")
        print("Supplement", p["concept"], flush=True)
    pd.DataFrame(rows).to_csv(OUT / "supplement.csv", index=False)
    (OUT / "concept_configs.json").write_text(json.dumps(selected_configs, indent=2), encoding="utf-8")
    # One predeclared portfolio of the two strongest concepts by worst-past-period R.
    # Selection uses training/validation only, and never selects by 2026 outcomes.
    chosen = selected.head(2).concept.tolist()
    if len(chosen) == 2:
        merged = pd.concat([signals[name] for name in chosen], ignore_index=True)
        merged = merged.sort_values(["signal_time", "concept"], kind="stable").drop_duplicates("signal_time")
        days = merged.signal_time.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
        merged = merged[merged.groupby(days).cumcount() < 2]
        results = []
        for spread, slippage in [(0.3, 0.05), (0.6, 0.1), (0.9, 0.15)]:
            t = execute(merged, m5, spread=spread, slippage=slippage)
            results.append(dict(concepts="+".join(chosen), spread=spread,
                                slippage=slippage, **summarize(t, f)))
            if spread == 0.3:
                t.to_csv(OUT / "combined_trades.csv", index=False)
        pd.DataFrame(results).to_csv(OUT / "combined.csv", index=False)
    # Dependence-aware uncertainty on the fixed past-selected concept evaluations.
    intervals = {}
    rng = np.random.default_rng(20261015)
    for name in signals:
        t = pd.read_csv(OUT / f"concept_{name}_trades.csv")
        t = t[t.filled].copy()
        t["exit_time"] = pd.to_datetime(t.exit_time, utc=True)
        t = t[t.exit_time >= "2026-01-01"]
        t["month"] = t.exit_time.dt.tz_localize(None).dt.to_period("M")
        monthly = t.groupby("month").r.agg(["sum", "count"]).reindex(pd.period_range("2026-01", "2026-10", freq="M"), fill_value=0)
        blocks = rng.integers(0, len(monthly), size=(10000, len(monthly)))
        total = monthly["sum"].to_numpy()[blocks].sum(axis=1)
        n = monthly["count"].to_numpy()[blocks].sum(axis=1)
        avg = total[n > 0]/n[n > 0]
        intervals[name] = {"test_month_block_bootstrap_avg_R_95pct": np.quantile(avg, [0.025, 0.975]).tolist() if len(avg) else [],
                           "limited_months": len(monthly), "search_adjusted": False}
    (OUT / "uncertainty.json").write_text(json.dumps(intervals, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
