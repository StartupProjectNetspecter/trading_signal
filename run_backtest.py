"""Backtest the gold SMC/ICT strategy on downloaded M5 data.

    python run_backtest.py
    python run_backtest.py --source mt5
Results: reports/summary.txt, reports/trades.csv, reports/equity.png
"""
import argparse

from goldbot.backtest.engine import simulate
from goldbot.backtest.report import write_report
from goldbot.config import load_config, resolve
from goldbot.data.store import load_m5, load_smt
from goldbot.strategy.asian_sweep import generate_signals
from goldbot.strategy.v2 import generate_v2
from goldbot.strategy.v3 import generate_v3


def main():
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=None)
    cfg = load_config(pre.parse_known_args()[0].config)
    ap = argparse.ArgumentParser(parents=[pre])
    ap.add_argument("--source", choices=["dukascopy", "mt5"], default=cfg["data"]["source"])
    args = ap.parse_args()
    cfg["data"]["source"] = args.source

    m5 = load_m5(cfg)
    print(f"Loaded {len(m5):,} M5 bars {m5.index[0]} -> {m5.index[-1]}")
    signals = generate_signals(m5, cfg, load_smt(cfg))
    print(f"Generated {len(signals)} signals")
    if signals.empty:
        print("No signals - check config filters.")
        return
    trades = simulate(signals, m5, cfg)
    out = resolve(cfg["backtest"]["reports_dir"])
    print(write_report(trades, m5, cfg, out))

    # v2 (opening range + Bollinger), saved for the Telegram Performance button
    v2 = generate_v2(m5, cfg)
    if len(v2):
        v2 = v2[v2["filled"] & ~v2["outcome"].isin(["open"])].copy()
        v2.to_csv(out / "v2_trades.csv", index=False)
        r = v2["r"]
        loss = -r[r < 0].sum()
        print(f"\n== v2 ==\n{len(v2)} trades | win {100 * (r > 0).mean():.1f}% | PF {r[r > 0].sum() / loss:.2f} | {r.sum():+.1f}R")

    # Dip Buy (v3): TP 1R, no break-even, 6h max hold
    c3 = {**cfg, "backtest": {**cfg["backtest"], "max_hold_bars": 72},
          "strategy": {**cfg["strategy"], "partial_at_r": None, "breakeven_at_r": None}}
    v3 = simulate(generate_v3(m5, cfg), m5, c3)
    v3 = v3[v3["filled"]]
    v3.to_csv(out / "v3_trades.csv", index=False)
    r = v3["r"]
    loss = -r[r < 0].sum()
    print(f"\n== Dip Buy ==\n{len(v3)} trades | win {100 * (r > 0).mean():.1f}% | PF {r[r > 0].sum() / loss:.2f} | {r.sum():+.1f}R")
    print(f"\nSaved reports to {out}")


if __name__ == "__main__":
    main()
