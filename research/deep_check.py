"""Reproducible exploratory config audit: python -m research.deep_check.

Selection uses 2023-24 training and 2025 validation only. 2026 is evaluated
after selection, but is NOT pristine out-of-sample: prior reports exposed it.
Production configs are never overwritten. No downloads or live alerts.
"""
import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from goldbot.config import ROOT, load_config
from goldbot.data.store import load_m5
from goldbot.strategy.asian_sweep import generate_signals
from goldbot.backtest.engine import simulate
from goldbot.backtest.report import stats

OUT = ROOT / "reports" / "deep_check"
TRAIN_END = pd.Timestamp("2025-01-01", tz="UTC")
VALID_END = pd.Timestamp("2026-01-01", tz="UTC")


def variants():
    yield "baseline", {}
    for key, values in {
        "entry_model": ["ob", "fvg", "fvg_then_ob"],
        "htf_bias": ["none"],
        "htf_timeframe": ["4h", "1D"],
        "kill_zones": [["newyork"], ["london"]],
        "rr": [1.5, 2.5, 3.0],
        "sl_buffer_atr": [0.2, 0.5, 1.0],
        "entry_price": ["proximal"],
        "min_sweep_atr": [0.2],
        "min_displacement_atr": [0.5, 1.0],
        "swing_n": [3],
        "entry_expiry_bars": [24],
        "midnight_open_filter": [True],
        "tp_mode": ["liquidity"],
    }.items():
        for value in values:
            yield f"{key}={value}", {key: value}
    for rr in [1.5, 2.0, 3.0]:
        for buffer in [0.2, 0.5]:
            yield f"NY_OB_rr{rr}_buffer{buffer}", {
                "entry_model": "ob", "kill_zones": ["newyork"],
                "rr": rr, "sl_buffer_atr": buffer,
            }


def metrics(t):
    if t.empty:
        return {"trades": 0, "avg_R": np.nan, "total_R": 0,
                "profit_factor": np.nan, "max_drawdown_R": 0}
    return stats(t)


def periods(t):
    return {
        "train": t[(t.signal_time < TRAIN_END) & (t.exit_time < TRAIN_END)],
        "validation": t[(t.signal_time >= TRAIN_END) & (t.signal_time < VALID_END)
                        & (t.exit_time < VALID_END)],
        "test": t[t.signal_time >= VALID_END],
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for filename in ["config.yaml"]:
        cfg = load_config(ROOT / filename)
        m5 = load_m5(cfg)
        symbol = cfg["symbol"]
        audit = {
            "bars": len(m5), "start": str(m5.index.min()), "end": str(m5.index.max()),
            "duplicates": int(m5.index.duplicated().sum()),
            "sorted": bool(m5.index.is_monotonic_increasing),
            "missing_values": int(m5.isna().sum().sum()),
            "invalid_ohlc": int(((m5.high < m5[["open", "close", "low"]].max(axis=1))
                                | (m5.low > m5[["open", "close", "high"]].min(axis=1))).sum()),
            "gaps_over_5min": int((m5.index.to_series().diff() > pd.Timedelta(minutes=5)).sum()),
            "bars_by_year": m5.groupby(m5.index.year).size().to_dict(),
        }
        (OUT / f"{symbol}_data.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
        rows, configs, signals = [], {}, {}
        seen = set()
        for name, override in variants():
            candidate = copy.deepcopy(cfg)
            candidate["strategy"].update(override)
            key = json.dumps(candidate["strategy"], sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            sig = generate_signals(m5, candidate)
            t = simulate(sig, m5, candidate) if len(sig) else pd.DataFrame()
            row = {"variant": name, "signals": len(sig)}
            if len(t):
                for period, subset in periods(t).items():
                    row.update({f"{period}_{k}": v for k, v in metrics(subset).items()})
                row.update({f"overall_{k}": v for k, v in metrics(t).items()})
            rows.append(row)
            configs[name], signals[name] = candidate, sig
            print(f"{symbol} {name}: train={row.get('train_total_R')} "
                  f"validation={row.get('validation_total_R')}", flush=True)
        df = pd.DataFrame(rows)
        # Require some support in both selection periods. Never rank on 2026.
        eligible = df[(df.train_trades >= 20) & (df.validation_trades >= 10)].copy()
        eligible["score"] = eligible[["train_avg_R", "validation_avg_R"]].min(axis=1)
        eligible = eligible.sort_values(["score", "validation_total_R"], ascending=False)
        df.to_csv(OUT / f"{symbol}_variants.csv", index=False)
        eligible.to_csv(OUT / f"{symbol}_ranking.csv", index=False)
        if eligible.empty:
            print(f"{symbol}: insufficient trades for selection", flush=True)
            continue
        best = eligible.iloc[0]["variant"]
        selected = configs[best]
        (OUT / f"{symbol}_candidate.yaml").write_text(
            "# Highest selection score among candidates meeting minimum counts.\n"
            "# This does NOT establish profitability or suitability for live use.\n" +
            yaml.safe_dump(selected, sort_keys=False), encoding="utf-8")
        stress = []
        for spread_multiplier, fee_pct in [(1, cfg["backtest"].get("commission_pct", 0)),
                                            (2, cfg["backtest"].get("commission_pct", 0)),
                                            (3, cfg["backtest"].get("commission_pct", 0))]:
            c = copy.deepcopy(selected)
            c["backtest"]["spread_usd"] *= spread_multiplier
            c["backtest"]["commission_pct"] = fee_pct
            t = simulate(signals[best], m5, c)
            t.to_csv(OUT / f"{symbol}_selected_spread{spread_multiplier}_fee{fee_pct}.csv", index=False)
            for period, subset in periods(t).items():
                stress.append({"variant": best, "spread_multiplier": spread_multiplier,
                               "commission_pct_per_side": fee_pct, "period": period, **metrics(subset)})
        pd.DataFrame(stress).to_csv(OUT / f"{symbol}_stress.csv", index=False)
        print(f"SELECTED {symbol}: {best}", flush=True)


if __name__ == "__main__":
    main()
