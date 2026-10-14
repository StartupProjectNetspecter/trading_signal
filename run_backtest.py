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
    print(f"\nSaved reports to {out}")


if __name__ == "__main__":
    main()
