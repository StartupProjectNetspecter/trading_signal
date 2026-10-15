"""v2 must reproduce Codex's verified research trades exactly (tests/fixtures/v2_reference).

    python -m tests.test_v2_parity
"""
import numpy as np
import pandas as pd

from goldbot.config import ROOT, load_config
from goldbot.data.store import load_m5
from goldbot.strategy import v2

REF = ROOT / "tests" / "fixtures" / "v2_reference"


def test_v2_parity():
    cfg = load_config()
    cfg["news"]["events_file"] = str(ROOT / "tests" / "fixtures" / "news_events_v1.csv")  # calendar used by the research
    cfg["news"]["block_nfp"] = False
    m5 = load_m5(cfg)
    m5 = m5[m5.index < "2026-10-14 18:00"]
    f = v2.features(m5, cfg)
    setups = {"opening_range": v2.opening_range_setups(m5, f), "bollinger": v2.bollinger_setups(m5, f)}
    # original Codex parameters (before our improvement filters / 20-minute expiry)
    original = {"v2a": dict(v2.MODELS["v2a"], vol_min=0.0, expiry=6), "v2b": dict(v2.MODELS["v2b"], adx_min=25.0)}
    for key, k in (("v2a", 7940), ("v2b", 5361)):
        mine = v2.run_model(f, setups[original[key]["source"]], original[key])
        ref = pd.read_csv(REF / f"shortlist_detail_{k}.csv")
        m = mine.merge(ref, on="signal_i", suffixes=("", "_ref"))
        m = m[m["outcome_ref"] != "expired"] if len(m) else m
        assert len(mine) == len(ref), f"{key}: {len(mine)} trades vs reference {len(ref)}"
        assert np.allclose(m["entry"], m["entry_ref"]) and np.allclose(m["sl"], m["sl_ref"]) and np.allclose(m["tp"], m["tp_ref"])
        assert np.allclose(m["r"], m["r_ref"], atol=1e-6), f"{key}: R differs"
        print(f"  {key}: {len(mine)} trades identical to the research engine")


if __name__ == "__main__":
    test_v2_parity()
    print("PASS test_v2_parity")
