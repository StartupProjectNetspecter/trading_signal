"""Does v1 (tuned on gold only) work on other markets with NO re-tuning?  python -m research.multi_market_v1"""
import copy

import pandas as pd

from goldbot.backtest.engine import simulate
from goldbot.backtest.report import stats
from goldbot.config import load_config
from goldbot.data.store import load_m5
from goldbot.strategy.asian_sweep import generate_signals

# conservative spreads (~1.5-2x the MT5 quote on 2026-10-15)
MARKETS = {"XAUUSD": 0.30, "XAGUSD": 0.03, "EURUSD": 0.00008, "US500": 0.70, "USTEC": 2.0}


def main():
    base = load_config()
    rows = []
    for sym, spread in MARKETS.items():
        cfg = copy.deepcopy(base)
        cfg["symbol"] = sym
        cfg["backtest"]["spread_usd"] = spread
        cfg["strategy"]["smt_symbol"] = None
        cfg["strategy"]["price_digits"] = 5 if sym == "EURUSD" else 3 if sym == "XAGUSD" else 2
        if sym != "XAUUSD":
            cfg["strategy"]["min_risk_usd"] = 0.0  # gold's $1 minimum makes no sense on other prices; SL is >= 0.5 ATR anyway
        m5 = load_m5(cfg, sym)
        t = simulate(generate_signals(m5, cfg, None), m5, cfg)
        f = t[t["filled"]]
        per = pd.cut(f["signal_time"], [pd.Timestamp("2000", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC"),
                                        pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2100", tz="UTC")], labels=["2023-24", "2025", "2026"])
        s = stats(t)
        row = {"market": sym, "signals/wk": round(len(t) / 197, 2), "trades/wk": round(s.get("trades", 0) / 197, 2),
               "win%": s.get("win_rate_%"), "PF": s.get("profit_factor"), "total_R": s.get("total_R"), "maxDD%": s.get("max_drawdown_%")}
        for p in ["2023-24", "2025", "2026"]:
            r = f["r"][per == p]
            loss = -r[r < 0].sum()
            row[f"PF {p}"] = round(r[r > 0].sum() / loss, 2) if loss else None
        rows.append(row)
    pd.set_option("display.width", 200)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
