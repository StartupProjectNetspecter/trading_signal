"""Test strategy variants fairly: compare on in-sample, confirm on out-of-sample.

    python -m research.experiments
A variant is only worth keeping if it improves BOTH periods.
"""
import copy
from multiprocessing import Pool

import pandas as pd

from goldbot.backtest.engine import simulate
from goldbot.config import load_config
from goldbot.data.store import load_m5
from goldbot.strategy.asian_sweep import generate_signals

SPLIT = pd.Timestamp("2025-07-01", tz="UTC")

VARIANTS = {
    "baseline": {},
    "htf 4h": {"htf_timeframe": "4h"},
    "htf 1D": {"htf_timeframe": "1D"},
    "no htf bias": {"htf_bias": "none"},
    "NY kill zone only": {"kill_zones": ["newyork"]},
    "London only": {"kill_zones": ["london"]},
    "OB entry only": {"entry_model": "ob"},
    "FVG entry only": {"entry_model": "fvg"},
    "proximal entry": {"entry_price": "proximal"},
    "TP = Asian liquidity": {"tp_mode": "liquidity"},
    "RR 1.5": {"rr": 1.5},
    "RR 3": {"rr": 3.0},
    "displacement 0.5 ATR": {"min_displacement_atr": 0.5},
    "displacement 1.0 ATR": {"min_displacement_atr": 1.0},
    "midnight open filter": {"midnight_open_filter": True},
    "sweep >= 0.2 ATR": {"min_sweep_atr": 0.2},
    "swing_n 3": {"swing_n": 3},
    "choch window 3h": {"max_bars_sweep_to_choch": 36},
    "SL buffer 0.5 ATR": {"sl_buffer_atr": 0.5},
    "order expiry 2h": {"entry_expiry_bars": 24},
}

_M5 = None
_CFG = None


def _init():
    global _M5, _CFG
    _CFG = load_config()
    _M5 = load_m5(_CFG)


def _metrics(t):
    t = t[t["filled"]] if len(t) else t
    if len(t) == 0:
        return {"n": 0, "win%": 0, "avgR": 0, "totR": 0, "PF": 0}
    r = t["r"]
    loss = -r[r < 0].sum()
    return {
        "n": len(r),
        "win%": round(100 * (r > 0).mean(), 1),
        "avgR": round(r.mean(), 3),
        "totR": round(r.sum(), 1),
        "PF": round(r[r > 0].sum() / loss, 2) if loss else 99,
    }


def run(item):
    name, overrides = item
    cfg = copy.deepcopy(_CFG)
    cfg["strategy"].update(overrides)
    sig = generate_signals(_M5, cfg)
    trades = simulate(sig, _M5, cfg) if len(sig) else pd.DataFrame(columns=["filled", "signal_time", "r"])
    is_t = trades[trades["signal_time"] < SPLIT] if len(trades) else trades
    oos_t = trades[trades["signal_time"] >= SPLIT] if len(trades) else trades
    row = {"variant": name}
    row.update({f"IS {k}": v for k, v in _metrics(is_t).items()})
    row.update({f"OOS {k}": v for k, v in _metrics(oos_t).items()})
    return row


def main(variants=VARIANTS):
    with Pool(initializer=_init) as pool:
        rows = pool.map(run, list(variants.items()))
    df = pd.DataFrame(rows).set_index("variant")
    pd.set_option("display.width", 200)
    print(f"In-sample: < {SPLIT:%Y-%m-%d}   Out-of-sample: >= {SPLIT:%Y-%m-%d}\n")
    print(df.to_string())
    return df


if __name__ == "__main__":
    main()
