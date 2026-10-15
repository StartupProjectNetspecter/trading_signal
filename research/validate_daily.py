"""Check full-vs-prefix feature/signal equality and diagnose legacy research causality."""
import copy
import json

import numpy as np
import pandas as pd

from goldbot.config import load_config
from goldbot.data.store import load_m5
from goldbot.strategy.asian_sweep import generate_signals
from goldbot.strategy.daily_models import generate_daily
from research.causal_gold import CONCEPTS, BAR, features, proposals, generate
from research.gold_daily_audit import OUT


def main():
    cfg = load_config()
    m5 = load_m5(cfg).iloc[-288*90:]
    f = features(m5, cfg)
    cuts = [5000, 11003, 17007, len(m5)-7]
    full = {}
    funnels = {}
    for concept in CONCEPTS:
        p = dict(concept=concept, n=2, session="london_ny", bias="h1_bos", buffer=0.5, rr=1)
        diag = {}
        full[concept] = generate(f, proposals(f, concept, 2), p, diag)
        funnels[concept] = diag
    checks = []
    for cut in cuts:
        part = m5.iloc[:cut]
        fp = features(part, cfg)
        for col in ["s2_high", "s2_low", "s2_high_label", "s2_low_label", "s2_trend",
                    "s3_trend", "h1_bos", "h1_hhhl", "ema21", "ema55", "rsi", "atr"]:
            pd.testing.assert_series_equal(fp[col], f[col].iloc[:cut])
        end = part.index[-1]+BAR
        for concept in CONCEPTS:
            p = dict(concept=concept, n=2, session="london_ny", bias="h1_bos", buffer=0.5, rr=1)
            actual = generate(fp, proposals(fp, concept, 2), p)
            expected = full[concept]
            if len(expected):
                expected = expected[expected.signal_time <= end]
            pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True))
            checks.append(dict(concept=concept, cut=str(end), passed=True, n=len(actual)))
    legacy = {}
    cont_cfg = copy.deepcopy(cfg)
    cont_cfg["strategy"].update(models=["reversal", "continuation"], max_signals_per_day=3)
    sb_cfg = copy.deepcopy(cfg)
    sb_cfg["strategy"].update(daily_models=["silver_bullet"], silver_bullet={
        "windows": [["03:00", "04:00"], ["10:00", "11:00"], ["14:00", "15:00"]],
        "min_fvg_atr": 0.1, "min_displacement_atr": 0.5, "pre_window_bars": 12,
        "require_sweep": False, "sl_at": "fvg", "expiry_after_window_bars": 6})
    for name, gen, c in [("legacy_combined_continuation", generate_signals, cont_cfg),
                          ("legacy_silver_bullet", generate_daily, sb_cfg)]:
        fs = gen(m5, c)
        failures = []
        # Cut immediately after sampled signal bars, where future-window expiry is exposed.
        positions = [int(m5.index.searchsorted(t)) for t in fs.signal_time.iloc[:12]] if len(fs) else cuts
        for cut in positions:
            part = gen(m5.iloc[:cut], c)
            expected = fs[fs.signal_time <= m5.index[cut-1]+BAR] if len(fs) else fs
            try:
                pd.testing.assert_frame_equal(part.reset_index(drop=True), expected.reset_index(drop=True))
            except AssertionError:
                failures.append(str(m5.index[cut-1]+BAR))
        legacy[name] = dict(checks=len(positions), failed_prefix_times=failures)
    OUT.mkdir(parents=True, exist_ok=True)
    result = dict(causal_checks=checks, legacy_checks=legacy, recent_90day_funnels=funnels)
    (OUT / "causality.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(dict(causal_checks_passed=len(checks), legacy_checks=legacy), indent=2), flush=True)


if __name__ == "__main__":
    main()
