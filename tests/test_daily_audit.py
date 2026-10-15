"""Meaningful causal-structure and execution edge cases, independent of live v1."""
import unittest

import numpy as np
import pandas as pd

from research.causal_gold import confirmed_structure, execute, features, proposals


def candles(highs, lows, opens=None, closes=None):
    h, l = np.array(highs, float), np.array(lows, float)
    mid = (h+l)/2
    return pd.DataFrame({"open": mid if opens is None else opens, "high": h,
                         "low": l, "close": mid if closes is None else closes,
                         "volume": 1}, index=pd.date_range("2025-01-06 14:00", periods=len(h), freq="5min", tz="UTC"))


def signal(df, d="BUY", entry=100, sl=98, tp=102, order="limit", at=0, expiry=15):
    return dict(signal_time=df.index[at], expiry_time=df.index[at]+pd.Timedelta(minutes=expiry),
                direction=d, entry=entry, sl=sl, tp=tp, order=order)


class StructureTests(unittest.TestCase):
    def test_opening_range_requires_complete_bars_and_has_real_setups(self):
        df = candles([101]*30, [99]*30, [100]*30, [100]*30)
        # 14:00 UTC is 09:00 NY; start at 07:00 NY to include a full OR.
        df.index = pd.date_range("2025-01-06 12:00", periods=30, freq="5min", tz="UTC")
        df.iloc[21, df.columns.get_loc("high")] = 103
        df.iloc[21, df.columns.get_loc("close")] = 102
        cfg = {"news": {"block_nfp": False, "block_before_min": 30, "block_after_min": 60}}
        f = features(df, cfg)
        raw = proposals(f, "opening_range")
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0]["entry"], 100.5)
        self.assertEqual(raw[0]["stop_ref"], 99)
        self.assertEqual(len(proposals(features(df.iloc[:20], cfg), "opening_range")), 0)

    def test_confirmation_and_higher_high(self):
        df = candles([10, 13, 10, 11, 15, 11, 12], [8, 9, 7, 9, 10, 8, 10])
        s = confirmed_structure(df, 1)
        self.assertTrue(np.isnan(s.high.iloc[1]))
        self.assertEqual(s.high.iloc[2], 13)
        self.assertEqual(s.high_label.iloc[5], "HH")
        self.assertEqual(s.previous_high.iloc[5], 13)
        self.assertEqual(s.low_label.iloc[6], "HL")
        self.assertEqual(s.trend.iloc[6], 1)

    def test_equal_levels_are_neutral(self):
        df = candles([10, 13, 10, 11, 13, 11, 12], [8, 9, 7, 9, 10, 7, 10])
        s = confirmed_structure(df, 1)
        self.assertEqual(s.high_label.iloc[5], "EH")
        self.assertEqual(s.low_label.iloc[6], "EL")
        self.assertEqual(s.trend.iloc[6], 0)

    def test_lower_high_lower_low(self):
        df = candles([10, 15, 10, 11, 13, 11, 12], [8, 9, 7, 9, 10, 6, 10])
        s = confirmed_structure(df, 1)
        self.assertEqual(s.high_label.iloc[5], "LH")
        self.assertEqual(s.low_label.iloc[6], "LL")
        self.assertEqual(s.trend.iloc[6], -1)

    def test_every_prefix_identical(self):
        rng = np.random.default_rng(7)
        mid = 100+np.cumsum(rng.normal(size=100))
        df = candles(mid+1, mid-1)
        for n in [1, 2, 3]:
            full = confirmed_structure(df, n)
            for cut in range(1, len(df)):
                pd.testing.assert_frame_equal(confirmed_structure(df.iloc[:cut], n), full.iloc[:cut])


class ExecutionTests(unittest.TestCase):
    def test_no_profit_on_fill_bar(self):
        df = candles([103, 103], [99, 100], [101, 101], [101, 102])
        t = execute(pd.DataFrame([signal(df)]), df, spread=0, slippage=0)
        self.assertEqual(t.outcome.iloc[0], "tp")
        self.assertEqual(t.exit_time.iloc[0], df.index[1]+pd.Timedelta(minutes=5))
        self.assertEqual(t.r.iloc[0], 1)

    def test_stop_wins_ambiguous_bar(self):
        df = candles([103, 103], [97, 100], [101, 101], [101, 102])
        t = execute(pd.DataFrame([signal(df)]), df, spread=0, slippage=0)
        self.assertEqual(t.r.iloc[0], -1)

    def test_gap_stop_and_slippage(self):
        df = candles([101, 97], [99, 95], [100, 96], [100, 96])
        t = execute(pd.DataFrame([signal(df)]), df, spread=0, slippage=0.1)
        self.assertAlmostEqual(t.r.iloc[0], -2.05)

    def test_invalid_gap_does_not_divide_by_negative_risk(self):
        df = candles([99, 101], [95, 99], [96, 100], [97, 100])
        t = execute(pd.DataFrame([signal(df)]), df, spread=0, slippage=0)
        self.assertFalse(t.filled.iloc[0])
        self.assertEqual(t.outcome.iloc[0], "invalid_gap")

    def test_market_uses_next_bar_open_cost(self):
        df = candles([101, 103], [99, 100], [100, 101], [100, 102])
        t = execute(pd.DataFrame([signal(df, order="market")]), df, spread=0.3, slippage=0.1)
        self.assertAlmostEqual(t.fill_price.iloc[0], 100.4)
        self.assertAlmostEqual(t.r.iloc[0], (102-100.4)/(100.4-98))

    def test_short_uses_ask_exit(self):
        df = candles([101, 100], [99, 97], [100, 99], [100, 98])
        t = execute(pd.DataFrame([signal(df, d="SELL", sl=102, tp=98)]), df, spread=0.3, slippage=0)
        self.assertEqual(t.outcome.iloc[0], "tp")
        self.assertEqual(t.r.iloc[0], 1)

    def test_commission_reduces_net_r(self):
        df = candles([101, 103], [99, 100], [100, 101], [100, 102])
        t = execute(pd.DataFrame([signal(df)]), df, spread=0, slippage=0, commission=0.2)
        self.assertAlmostEqual(t.r.iloc[0], 0.9)

    def test_capacity_does_not_overlap_positions(self):
        df = candles([101, 101, 103], [99, 99, 100], [100, 100, 101], [100, 100, 102])
        t = execute(pd.DataFrame([signal(df), signal(df, at=1)]), df, spread=0, slippage=0)
        self.assertEqual(t.outcome.iloc[1], "capacity")

    def test_expiry_uses_elapsed_time(self):
        df = candles([101, 101], [100.5, 99], [101, 100], [101, 100])
        df.index = pd.DatetimeIndex([df.index[0], df.index[0]+pd.Timedelta(hours=2)])
        t = execute(pd.DataFrame([signal(df, expiry=15)]), df, spread=0, slippage=0)
        self.assertFalse(t.filled.iloc[0])
        self.assertEqual(t.outcome.iloc[0], "expired")


if __name__ == "__main__":
    unittest.main()
