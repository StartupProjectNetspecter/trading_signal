"""Hand-calculated management/price cases for the compiled research engine."""
import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from research.search_10k import BUILD, PARAMS, DTYPE, compile_engine


class EngineCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compile_engine()

    def execute(self, high, low, *, management=0, rr=2, d=1, opens=None,
                spread=0, slip=0, fee=0, order=0, gaps=None, news=None):
        n = len(high)
        time = np.arange(n, dtype="<i8")*300+1736172000
        if gaps:
            for i, seconds in gaps.items():
                time[i:] += seconds
        o = np.array(opens or [100.0]*n, dtype="<f8")
        arrays = [o, np.array(high, dtype="<f8"), np.array(low, dtype="<f8"), o.copy(),
                  np.full(n, 2.0, dtype="<f8"), np.full(n, 50.0, dtype="<f8"),
                  np.full(n, 20.0, dtype="<f8"), np.full(n, 0.5, dtype="<f8"), np.ones(n, dtype="<f8")]
        keys = [np.full(n, 600, dtype="<i4"), np.full(n, 20250106, dtype="<i4"),
                np.zeros(n, dtype="<i4"), np.array(news or [0]*n, dtype="<i4")]
        keys += [np.ones(n, dtype="<i4") for _ in range(4)]
        keys += [np.zeros(n, dtype="<i4"), np.zeros(n, dtype="<i4")]
        raw = np.zeros(1, dtype=DTYPE)
        raw[0] = (0, d, 100.0, 98.0 if d == 1 else 102.0, order, 12, -1, 100, 100, 255)
        p = dict(id=0, source=0, bias=0, start=0, end=1439, cap=2, cooldown=0,
                 stop_mode=0, buffer=0, rr=rr, min_risk=1, max_risk=8, expiry=12,
                 hold=1, management=management, direction=0, adx_min=0, adx_max=100,
                 body=0, vol_min=0, vol_max=100, q1=0, q2=0, flags=0)
        with tempfile.TemporaryDirectory(dir=BUILD) as tmp:
            tmp = Path(tmp)
            with open(tmp / "data.bin", "wb") as dest:
                dest.write(struct.pack("<4i", 20261015, n, 1, 1))
                time.tofile(dest)
                for arr in arrays+keys:
                    arr.tofile(dest)
                dest.write(struct.pack("<2i", 1, 1))
                raw.tofile(dest)
            pd.DataFrame([p])[PARAMS].to_csv(tmp / "params.csv", index=False)
            subprocess.run([str(BUILD / "GoldSearch.exe"), str(tmp / "data.bin"), str(tmp / "params.csv"),
                            str(tmp / "result.csv"), str(spread), str(slip), str(fee), str(tmp / "detail")],
                           check=True, capture_output=True)
            return pd.read_csv(tmp / "detail_0.csv").iloc[0]

    def test_fill_bar_cannot_take_profit(self):
        row = self.execute([101, 105, 105], [99, 99, 99])
        self.assertEqual(row.exit_i, 2)
        self.assertEqual(row.r, 2)

    def test_stop_first_ambiguous(self):
        row = self.execute([101, 105, 105], [99, 97, 99])
        self.assertEqual(row.outcome, "sl")
        self.assertEqual(row.r, -1)

    def test_partial_and_target_pays_one_and_half_r(self):
        row = self.execute([101, 101, 105], [99, 99, 99], management=2)
        self.assertEqual(row.outcome, "tp+partial")
        self.assertEqual(row.r, 1.5)

    def test_partial_then_break_even(self):
        row = self.execute([101, 101, 103, 101], [99, 99, 99, 99], management=2)
        self.assertEqual(row.outcome, "be+partial")
        self.assertEqual(row.r, 0.5)

    def test_break_even_activates_on_next_bar(self):
        row = self.execute([101, 101, 103, 101], [99, 99, 99, 99], management=1)
        self.assertEqual(row.exit_i, 3)
        self.assertEqual(row.r, 0)

    def test_no_partial_above_final_target(self):
        row = self.execute([101, 101, 105], [99, 99, 99], management=2, rr=0.75)
        self.assertEqual(row.outcome, "tp")
        self.assertEqual(row.r, 0.75)

    def test_market_ask_and_slippage(self):
        row = self.execute([101, 102, 105], [99, 99, 100], spread=0.3, slip=0.1)
        self.assertAlmostEqual(row.fill_price, 100.4)
        self.assertAlmostEqual(row.r, (104-100.4)/(100.4-98))

    def test_short_target_requires_ask_touch(self):
        row = self.execute([101, 101, 100, 100], [99, 99, 95.9, 95.5], d=-1, spread=0.3)
        self.assertEqual(row.exit_i, 3)
        self.assertAlmostEqual(row.r, 2)

    def test_news_cancels_pending_before_fill(self):
        row = self.execute([101, 101, 103], [100.5, 99, 99], order=1, news=[0, 1, 0])
        self.assertEqual(row.outcome, "news_cancel")
        self.assertEqual(row.fill_i, -1)

    def test_gap_stop_adverse_open(self):
        row = self.execute([101, 101, 97], [99, 99, 95], opens=[100, 100, 96], slip=0.1)
        self.assertEqual(row.outcome, "sl")
        self.assertAlmostEqual(row.exit_price, 95.9)

    def test_invalid_fill_never_divides_by_zero(self):
        row = self.execute([101, 99, 101], [99, 95, 99], opens=[100, 96, 100])
        self.assertEqual(row.fill_i, -1)
        self.assertEqual(row.outcome, "invalid_gap")

    def test_fee_in_correct_per_ounce_units(self):
        row = self.execute([101, 101, 105], [99, 99, 99], fee=0.005)
        self.assertAlmostEqual(row.r, 2-0.005/2)


if __name__ == "__main__":
    unittest.main()
