"""v1 must never change: its backtest on the same data must give the same numbers.

    python -m tests.test_v1_regression
"""
from goldbot.backtest.engine import simulate
from goldbot.backtest.report import stats
from goldbot.config import ROOT, load_config
from goldbot.data.store import load_m5, load_smt
from goldbot.strategy.asian_sweep import generate_signals

V1 = {"trades": 70, "win_rate_%": 52.9, "profit_factor": 1.38, "total_R": 12.2, "max_drawdown_%": 6.1}


def test_v1_unchanged():
    cfg = load_config(ROOT / "config.yaml")
    # pinned news list: this test guards the v1 CODE; news-calendar updates are checked separately
    cfg["news"]["events_file"] = str(ROOT / "tests" / "fixtures" / "news_events_v1.csv")
    cfg["news"]["block_nfp"] = False
    m5 = load_m5(cfg)
    m5 = m5[m5.index < "2026-10-14 18:00"]  # fixed data window so new downloads don't change the check
    s = stats(simulate(generate_signals(m5, cfg, load_smt(cfg)), m5, cfg))
    got = {k: s[k] for k in V1}
    assert got == V1, f"v1 results changed: {got} != {V1}"
    print(f"  v1 locked: {got}")


if __name__ == "__main__":
    test_v1_unchanged()
    print("PASS test_v1_unchanged")
