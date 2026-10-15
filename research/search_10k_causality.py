"""Truncation checks for all cached feature and algorithm source variants."""
import json

import numpy as np
import pandas as pd

from goldbot.config import load_config
from goldbot.data.store import load_m5
from research.search_10k import OUT, enrich, sources


def main():
    cfg = load_config()
    cfg["news"]["events_file"] = str(OUT / "news_events.csv")
    m5 = load_m5(cfg).iloc[-288*30:]
    f = enrich(m5, cfg)
    full, labels = sources(m5, f, cfg)
    checks = []
    for cut in [3503, 6001, len(m5)-5]:
        part = m5.iloc[:cut]
        fp = enrich(part, cfg)
        for col in ["atr", "rsi", "adx", "body", "volratio", "s2_high", "s2_low", "s4_trend", "s5_trend",
                    "h1_bos", "h1_hhhl", "m15_bos", "m15_hhhl"]:
            pd.testing.assert_series_equal(fp[col], f[col].iloc[:cut])
        raw, part_labels = sources(part, fp, cfg)
        assert len(raw) == len(full)
        for i, arr in enumerate(raw):
            expected = full[i][full[i]["i"] < cut]
            assert len(arr) == len(expected), (cut, labels[i], len(arr), len(expected))
            for col in arr.dtype.names:
                if arr.dtype[col].kind == "f":
                    np.testing.assert_allclose(arr[col], expected[col], rtol=1e-10, atol=1e-8, equal_nan=True)
                else:
                    np.testing.assert_array_equal(arr[col], expected[col])
            checks.append(dict(cut=str(part.index[-1]), source=i, family=labels[i]["family"],
                               raw_setups=len(arr), passed=True))
    (OUT / "causality_checks.json").write_text(json.dumps(dict(checks=checks, passed=True), indent=2), encoding="utf-8")
    print("PASSED", len(checks), "source-prefix checks across all 54 variants", flush=True)


if __name__ == "__main__":
    main()
