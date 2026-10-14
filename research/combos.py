"""Combinations of the filters that improved BOTH periods in research/experiments.py."""
from research.experiments import main

ob = {"entry_model": "ob"}
ny = {"kill_zones": ["newyork"]}
liq = {"tp_mode": "liquidity"}
sw = {"min_sweep_atr": 0.2}
sl = {"sl_buffer_atr": 0.5}

COMBOS = {
    "baseline": {},
    "OB + liquidity TP": {**ob, **liq},
    "OB + SL0.5": {**ob, **sl},
    "OB + sweep0.2 + SL0.5": {**ob, **sw, **sl},
    "OB + SL0.5 + liquidity TP": {**ob, **sl, **liq},
    "NY + OB + SL0.5": {**ny, **ob, **sl},
    "NY + OB + SL0.5 + liq TP": {**ny, **ob, **sl, **liq},
    "all five": {**ny, **ob, **sl, **liq, **sw},
}

if __name__ == "__main__":
    main(COMBOS)
