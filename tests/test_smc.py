"""Sanity tests. Run:  python -m tests.test_smc"""
import numpy as np
import pandas as pd

from goldbot.config import load_config
from goldbot.smc.fvg import find_fvgs, latest_fvg
from goldbot.smc.structure import market_structure
from goldbot.smc.swings import last_confirmed, swing_points


def bars(highs, lows):
    idx = pd.date_range("2025-01-06", periods=len(highs), freq="5min", tz="UTC")
    h, l = np.array(highs, float), np.array(lows, float)
    return pd.DataFrame({"open": (h + l) / 2, "high": h, "low": l, "close": (h + l) / 2}, index=idx)


def test_swings_confirmed_late():
    h = np.array([1, 2, 5, 2, 1, 1, 1], float)
    sh, _ = swing_points(h, h - 0.5, 2)
    assert sh[2] and sh.sum() == 1
    level, index = last_confirmed(h, sh, 2)
    assert np.isnan(level[3]), "swing must not be known before j + n"
    assert level[4] == 5 and index[4] == 2


def test_fvg():
    df = bars([10, 12, 15, 16], [9, 10, 13, 14])  # bar2 low 13 > bar0 high 10
    f = find_fvgs(df)
    assert f.iloc[0]["direction"] == 1 and f.iloc[0]["bottom"] == 10 and f.iloc[0]["top"] == 13
    assert latest_fvg(df["high"].to_numpy(), df["low"].to_numpy(), 0, 3, 1) == (12, 14, 3)


def test_structure_choch():
    highs = [10, 11, 13, 11, 10, 9, 8, 9, 10, 12, 14, 15]
    lows = [9, 10, 12, 10, 9, 7, 6, 7, 9, 11, 13, 14]
    df = bars(highs, lows)
    df["close"] = df["high"] - 0.1
    ms = market_structure(df, n=2)
    ups = ms[ms["event"].str.endswith("UP")]
    assert len(ups) and ups["level"].iloc[0] == 13


def test_no_lookahead():
    """Signals generated on truncated data must equal signals on the full data up to the cut."""
    from goldbot.data.store import load_m5, load_smt
    from goldbot.strategy.asian_sweep import generate_signals

    cfg = load_config()
    try:
        m5 = load_m5(cfg)
    except FileNotFoundError:
        print("  (skipped: no data downloaded yet)")
        return
    cfg["strategy"].update(liquidity_levels=["asian", "pdh_pdl", "london"], max_signals_per_day=3)
    smt = load_smt(cfg)
    m5 = m5.iloc[-288 * 60 :]
    full = generate_signals(m5, cfg, smt)
    rng = np.random.default_rng(0)
    for cut in rng.integers(288 * 5, len(m5), 15):
        part = generate_signals(m5.iloc[:cut], cfg, smt[smt.index < m5.index[cut]] if smt is not None else None)
        end = m5.index[cut - 1] + pd.Timedelta(minutes=5)
        expect = full[full["signal_time"] <= end] if len(full) else full
        assert len(part) == len(expect), f"look-ahead detected at cut {m5.index[cut - 1]}"
        if len(part):
            pd.testing.assert_frame_equal(part.reset_index(drop=True), expect.reset_index(drop=True))
    print(f"  checked 15 cut points, {len(full)} signals")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
