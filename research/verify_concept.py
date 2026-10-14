"""Additional audit evidence; no production changes. Run after deep_check."""
import copy
import json

import numpy as np
import pandas as pd

from goldbot.config import ROOT, load_config
from goldbot.data.store import load_m5
from goldbot.strategy.asian_sweep import generate_signals
from goldbot.backtest.engine import simulate
from research.deep_check import OUT, metrics, periods


def main():
    evidence = {}
    for filename in ["config.yaml"]:
        cfg = load_config(ROOT / filename)
        m5 = load_m5(cfg)
        full = generate_signals(m5, cfg)
        checks = []
        for fraction in [0.15, 0.35, 0.55, 0.75, 0.95]:
            cut = int(len(m5) * fraction)
            end = m5.index[cut - 1] + pd.Timedelta(minutes=5)
            part = generate_signals(m5.iloc[:cut], cfg)
            expected = full[full.signal_time <= end]
            pd.testing.assert_frame_equal(part.reset_index(drop=True), expected.reset_index(drop=True))
            checks.append({"cut": str(end), "signals": len(part), "passed": True})
        mismatches = []
        recent = full[full.signal_time.dt.year == 2026]
        for s in recent.to_dict("records"):
            end = m5.index.searchsorted(s["signal_time"])
            window = m5.iloc[max(0, end - cfg["live"]["lookback_days"] * 288):end]
            rolling = generate_signals(window, cfg)
            match = rolling[(rolling.signal_time == s["signal_time"]) &
                            (rolling.direction == s["direction"])] if len(rolling) else rolling
            if match.empty or any(match.iloc[0][k] != s[k] for k in ["entry", "sl", "tp"]):
                mismatches.append(str(s["signal_time"]))
        trades = simulate(full, m5, cfg)
        t = trades[trades.filled].copy()
        d = np.where(t.direction == "BUY", 1, -1)
        risk = (t.fill_price - t.sl) * d
        evidence[cfg["symbol"]] = {
            "prefix_checks": checks,
            "live_rolling_signals_checked": len(recent),
            "live_rolling_mismatch_times": mismatches,
            "nonpositive_fill_risk": int((risk <= 0).sum()),
            "overlapping_positions": int(sum(
                ((t.fill_time < row.exit_time) & (t.exit_time > row.fill_time)).sum() - 1
                for row in t.itertuples()) // 2),
        }
        print(cfg["symbol"], evidence[cfg["symbol"]], flush=True)
    # Explore the small-sample gold candidate explicitly without promoting it.
    cfg = load_config()
    cfg["strategy"].update(entry_model="ob", kill_zones=["newyork"], rr=2.0, sl_buffer_atr=0.2)
    (OUT / "XAUUSD_paper_candidate.yaml").write_text(
        "# Exploratory paper candidate; too few trades for deployment.\n" +
        __import__("yaml").safe_dump(cfg, sort_keys=False), encoding="utf-8")
    m5 = load_m5(cfg)
    signals = generate_signals(m5, cfg)
    rows = []
    for spread in [0.30, 0.60, 0.90]:
        c = copy.deepcopy(cfg)
        c["backtest"]["spread_usd"] = spread
        trades = simulate(signals, m5, c)
        for period, t in {**periods(trades), "overall": trades}.items():
            rows.append({"spread": spread, "period": period, **metrics(t)})
        if spread == 0.3:
            trades.to_csv(OUT / "XAUUSD_paper_trades.csv", index=False)
            r = trades.loc[trades.filled, "r"].to_numpy()
            rng = np.random.default_rng(42)
            means = rng.choice(r, size=(10000, len(r)), replace=True).mean(axis=1)
            evidence["paper_candidate"] = {
                "bootstrap_mean_R_95pct": np.quantile(means, [0.025, 0.975]).tolist(),
                "bootstrap_limit": "IID trade bootstrap ignores dependence and search bias; exploratory only",
            }
    pd.DataFrame(rows).to_csv(OUT / "XAUUSD_paper_stress.csv", index=False)
    cfg["strategy"]["rr"] = 3.0
    cfg["backtest"]["risk_per_trade"] = 0.0025
    (OUT / "XAUUSD_paper_rr3.yaml").write_text(
        "# Exploratory only; six validation trades. Risk assumption: 0.25%.\n" +
        __import__("yaml").safe_dump(cfg, sort_keys=False), encoding="utf-8")
    signals = generate_signals(m5, cfg)
    rows = []
    for spread in [0.30, 0.60, 0.90]:
        c = copy.deepcopy(cfg)
        c["backtest"]["spread_usd"] = spread
        trades = simulate(signals, m5, c)
        for period, t in {**periods(trades), "overall": trades}.items():
            rows.append({"spread": spread, "period": period, **metrics(t)})
        if spread == 0.3:
            trades.to_csv(OUT / "XAUUSD_paper_rr3_trades.csv", index=False)
            r = trades.loc[trades.filled, "r"].to_numpy()
            rng = np.random.default_rng(42)
            means = rng.choice(r, size=(10000, len(r)), replace=True).mean(axis=1)
            evidence["paper_rr3"] = {
                "bootstrap_mean_R_95pct": np.quantile(means, [0.025, 0.975]).tolist(),
                "bootstrap_limit": "IID trade bootstrap ignores dependence and search bias; exploratory only",
            }
    pd.DataFrame(rows).to_csv(OUT / "XAUUSD_paper_rr3_stress.csv", index=False)
    (OUT / "integrity.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
