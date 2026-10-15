"""ICT liquidity-sweep model for gold, on M5 with higher-timeframe bias.

Long (short is the mirror image):
  1. Sell-side liquidity is marked: Asian low, previous day low (PDL), London low.
  2. Price trades through one of those levels (the sweep). A level only counts if it was
     still intact when the session started (e.g. PDL not already broken in the Asian session).
  3. Within N bars, an M5 candle CLOSES above the last confirmed swing high -> bullish CHoCH.
  4. The CHoCH happens inside an enabled kill zone, not near news, agrees with the
     higher-timeframe structure bias, and (optionally) shows SMT divergence vs silver:
     gold swept its low but silver did NOT sweep the same low.
  5. Limit BUY at the order block / FVG created by the displacement.
     SL below the sweep extreme + buffer, TP at fixed R or the nearest opposite liquidity.

Every value is computed only from bars that have CLOSED at the signal time (no look-ahead).
"""
import numpy as np
import pandas as pd

from goldbot.data.store import resample
from goldbot.smc.fvg import latest_fvg
from goldbot.smc.indicators import atr, to_np
from goldbot.smc.liquidity import asian_range
from goldbot.smc.order_block import find_order_block
from goldbot.smc.sessions import session_frame
from goldbot.smc.structure import market_structure
from goldbot.smc.swings import last_confirmed, swing_points

BAR = pd.Timedelta(minutes=5)


def htf_bias(m5, cfg):
    """Higher-timeframe structure trend (+1/-1/0) as known at the close of each M5 bar."""
    st = cfg["strategy"]
    if st["htf_bias"] == "none":
        return np.zeros(len(m5), dtype=np.int8)
    tf = st.get("htf_timeframe", "1h")
    htf = resample(m5, tf)
    ms = market_structure(htf, st["htf_swing_n"])
    right = pd.DataFrame({"t": htf.index + pd.Timedelta(tf), "trend": ms["trend"].to_numpy()})
    left = pd.DataFrame({"t": m5.index + BAR})
    merged = pd.merge_asof(left, right, on="t", direction="backward")
    return merged["trend"].fillna(0).to_numpy(np.int8)


class _Levels:
    """Per-session-day liquidity levels for one instrument (gold, or silver for SMT)."""

    def __init__(self, df, sess):
        self.h = df["high"].to_numpy(np.float64)
        self.l = df["low"].to_numpy(np.float64)
        day = sess["session_day"]
        self.asian = asian_range(df, sess)
        g = pd.DataFrame({"h": df["high"], "l": df["low"], "day": day}).groupby("day")
        daily = pd.DataFrame({"high": g["h"].max(), "low": g["l"].min()})
        self.prev_day = daily.shift(1)  # previous trading session day
        lm = sess["london_kz"].to_numpy()
        pos = np.arange(len(df))
        gl = pd.DataFrame({"h": self.h[lm], "l": self.l[lm], "pos": pos[lm], "day": day.to_numpy()[lm]}).groupby("day")
        self.london = pd.DataFrame({"high": gl["h"].max(), "low": gl["l"].min(), "end": gl["pos"].max()})

    def for_day(self, day, ds, enabled):
        """{(name, d): (price, available_from_pos)}; d=+1 means sell-side (below price, swept for longs)."""
        out = {}
        if "asian" in enabled and day in self.asian.index:
            r = self.asian.loc[day]
            out[("asian", 1)] = (r["asian_low"], int(r["end_pos"]) + 1)
            out[("asian", -1)] = (r["asian_high"], int(r["end_pos"]) + 1)
        if "pdh_pdl" in enabled and day in self.prev_day.index and not np.isnan(self.prev_day.loc[day, "low"]):
            out[("pdh_pdl", 1)] = (self.prev_day.loc[day, "low"], ds)
            out[("pdh_pdl", -1)] = (self.prev_day.loc[day, "high"], ds)
        if "london" in enabled and day in self.london.index:
            r = self.london.loc[day]
            out[("london", 1)] = (r["low"], int(r["end"]) + 1)
            out[("london", -1)] = (r["high"], int(r["end"]) + 1)
        return out

    def first_breach(self, price, d, start, end):
        """First bar in [start, end) that trades through the level, or -1."""
        seg = self.l[start:end] < price if d == 1 else self.h[start:end] > price
        k = np.flatnonzero(seg)
        return start + k[0] if len(k) else -1


class _Side:
    def __init__(self, direction):
        self.d = direction
        self.reset()
        self.done = False

    def reset(self):
        self.swept = False
        self.start = self.ext_idx = -1
        self.ext = self.choch = np.nan
        self.levels = []  # names of the levels swept in this sequence


def generate_signals(m5, cfg, smt_df=None):
    """smt_df: M5 frame of the correlated instrument (silver) for SMT divergence, or None."""
    st = cfg["strategy"]
    o, h, l, c = to_np(m5)
    n = st["swing_n"]
    sh, sl = swing_points(h, l, n)
    sh_level, sh_idx = last_confirmed(h, sh, n)
    sl_level, sl_idx = last_confirmed(l, sl, n)
    atr_ = atr(m5, st["atr_period"]).to_numpy()
    models = st.get("models", ["reversal"])
    m5_events = market_structure(m5, n)["event"].to_numpy() if "continuation" in models else None
    sess = session_frame(m5.index, cfg)
    bias = htf_bias(m5, cfg)
    enabled = st.get("liquidity_levels", ["asian"])
    gold = _Levels(m5, sess)
    asian = gold.asian
    silver = None
    if smt_df is not None:
        aligned = smt_df.reindex(m5.index).ffill()  # causal: last known silver bar
        silver = _Levels(aligned, sess)

    kz = np.zeros(len(m5), dtype=bool)
    for z in st.get("kill_zones", ["london", "newyork"]):
        kz |= sess[f"{z}_kz"].to_numpy()
    news = sess["news_block"].to_numpy()
    day_arr = sess["session_day"].to_numpy()
    close_time = m5.index + BAR

    day_starts = np.flatnonzero(np.r_[True, day_arr[1:] != day_arr[:-1]])
    day_ends = np.r_[day_starts[1:], len(m5)]

    signals = []
    for ds, de in zip(day_starts, day_ends):
        day = pd.Timestamp(day_arr[ds])
        if day.weekday() >= 5 or day not in asian.index:
            continue
        a_end = int(asian.loc[day, "end_pos"])
        scan_from = max(ds, a_end + 1)
        if scan_from >= de:
            continue
        midnight_open = o[scan_from]  # ICT: New York midnight open
        levels = gold.for_day(day, ds, enabled)
        silver_levels = silver.for_day(day, ds, enabled) if silver is not None else {}

        # a level only counts as liquidity if it was still intact when the scan starts
        active = {
            key: (price, max(avail, scan_from))
            for key, (price, avail) in levels.items()
            if not np.isnan(price) and gold.first_breach(price, key[1], avail, scan_from) < 0
        }

        sides = {1: _Side(1), -1: _Side(-1)}
        count = 0
        for i in range(scan_from, de) if "reversal" in models else ():
            if count >= st["max_signals_per_day"]:
                break
            a = atr_[i]
            if np.isnan(a):
                continue
            for d, s in sides.items():
                if s.done:
                    continue
                # --- 1) liquidity sweep
                extreme = l[i] if d == 1 else h[i]
                hit = [
                    nm
                    for (nm, dd), (price, avail) in active.items()
                    if dd == d and i >= avail and (price - extreme) * d > st["min_sweep_atr"] * a
                ]
                if hit and not s.swept:
                    s.swept, s.start, s.ext, s.ext_idx, s.levels = True, i, extreme, i, hit
                    lvl = sh_level[i] if d == 1 else sl_level[i]
                    if np.isnan(lvl):
                        lvl = h[max(i - 12, 0) : i].max() if d == 1 else l[max(i - 12, 0) : i].min()
                    s.choch = lvl
                elif s.swept:
                    s.levels += [nm for nm in hit if nm not in s.levels]
                    if (extreme - s.ext) * d < 0:
                        s.ext, s.ext_idx = extreme, i
                if not s.swept:
                    continue
                if i - s.start > st["max_bars_sweep_to_choch"]:
                    s.reset()
                    continue
                # --- 2) change of character
                if not (c[i] > s.choch if d == 1 else c[i] < s.choch):
                    continue
                sig = None
                if kz[i] and not news[i] and (st["htf_bias"] == "none" or bias[i] == d):
                    smt = _smt(silver, silver_levels, s, d, i)
                    if smt or not st.get("smt_filter"):
                        sig = _build_signal(d, i, s, o, h, l, c, a, levels, st, sess, bias, close_time, midnight_open, smt)
                s.reset()
                if sig:
                    s.done = True
                    count += 1
                    signals.append(sig)

        # --- continuation model: M5 structure break in the H1 trend direction, enter on the pullback
        if m5_events is not None:
            taken = {sg["signal_time"] for sg in signals}
            per_dir = {1: 0, -1: 0}
            for i in range(scan_from, de):
                if count >= st["max_signals_per_day"]:
                    break
                ev = m5_events[i]
                if not ev or not kz[i] or news[i] or np.isnan(atr_[i]):
                    continue
                d = 1 if ev.endswith("_UP") else -1
                if st.get("continuation_events", "bos") == "bos" and not ev.startswith("BOS"):
                    continue
                if bias[i] != d or per_dir[d] >= st.get("max_continuation_per_dir", 1) or close_time[i] in taken:
                    continue
                leg_idx = sl_idx[i] if d == 1 else sh_idx[i]  # the pullback extreme the move started from
                if leg_idx < 0:
                    continue
                leg = _Side(d)
                leg.ext, leg.ext_idx, leg.start, leg.levels = (l if d == 1 else h)[leg_idx], leg_idx, leg_idx, ["bos"]
                sig = _build_signal(d, i, leg, o, h, l, c, atr_[i], levels, st, sess, bias, close_time, midnight_open, False)
                if sig:
                    sig["model"] = "continuation"
                    per_dir[d] += 1
                    count += 1
                    signals.append(sig)
    out = pd.DataFrame(signals)
    if len(out):
        out["model"] = out["model"].fillna("reversal") if "model" in out else "reversal"
        out = out.sort_values("signal_time", kind="stable").reset_index(drop=True)
    return out


def _smt(silver, silver_levels, s, d, i):
    """SMT divergence: gold swept the level, silver did NOT sweep its equivalent level."""
    if silver is None:
        return False
    for name in s.levels:
        key = (name, d)
        if key not in silver_levels:
            continue
        price, avail = silver_levels[key]
        start = max(avail, s.start)  # silver must hold its level from gold's sweep until the CHoCH
        seg = silver.l[start : i + 1] if d == 1 else silver.h[start : i + 1]
        if len(seg) and not np.isnan(price) and ((seg.min() >= price) if d == 1 else (seg.max() <= price)):
            return True
    return False


def _build_signal(d, i, s, o, h, l, c, a, levels, st, sess, bias, close_time, midnight_open, smt):
    # displacement: the CHoCH candle must have a strong body
    if abs(c[i] - o[i]) < st.get("min_displacement_atr", 0.0) * a:
        return None
    if st["entry_price"] == "market":
        return _finish_signal(d, i, s, c[i], c[i], c[i], "market", o, c, a, levels, st, sess, bias, close_time, smt)
    # --- 3) entry zone: FVG from the displacement, else the order block
    zone, model = None, None
    f = latest_fvg(h, l, s.ext_idx + 2, i, d, st["min_fvg_atr"] * a) if st["entry_model"] != "ob" else None
    if f:
        zone, model = f, "fvg"
    elif st["entry_model"] in ("fvg_then_ob", "ob"):
        ob = find_order_block(o, h, l, c, max(s.ext_idx - 3, 0), i, d)
        if ob:
            zone, model = ob, "ob"
    if zone is None:
        return None
    bottom, top, _ = zone
    if st["entry_price"] == "ce":
        entry = (bottom + top) / 2
    else:
        entry = top if d == 1 else bottom
    if (d == 1 and entry >= c[i]) or (d == -1 and entry <= c[i]):
        return None  # entry must be a pullback
    # premium/discount vs midnight open: buy below it, sell above it
    if st.get("midnight_open_filter") and (entry - midnight_open) * d > 0:
        return None
    return _finish_signal(d, i, s, entry, bottom, top, model, o, c, a, levels, st, sess, bias, close_time, smt)


def _finish_signal(d, i, s, entry, bottom, top, model, o, c, a, levels, st, sess, bias, close_time, smt):
    # --- 4) risk
    sl = s.ext - d * st["sl_buffer_atr"] * a
    risk = (entry - sl) * d
    if risk < st["min_risk_usd"] or risk > st["max_risk_atr"] * a:
        return None
    if st["tp_mode"] == "liquidity":
        # nearest opposite liquidity that still pays at least min_rr
        targets = sorted(p * -d for (nm, dd), (p, _) in levels.items() if dd == -d and (p - entry) * d / risk >= st["min_rr"])
        if not targets:
            return None
        tp = -d * targets[0]
        rr = (tp - entry) * d / risk
    else:
        rr = st["rr"]
        tp = entry + d * rr * risk

    kz_name = "london" if sess["london_kz"].iat[i] else "newyork"
    return {
        "signal_time": close_time[i],
        "expiry_time": close_time[i] + st["entry_expiry_bars"] * BAR,
        "direction": "BUY" if d == 1 else "SELL",
        "entry": round(entry, st.get("price_digits", 2)),
        "sl": round(sl, st.get("price_digits", 2)),
        "tp": round(tp, st.get("price_digits", 2)),
        "rr": round(rr, 2),
        "session": kz_name,
        "liquidity": "+".join(s.levels),
        "entry_model": model,
        "order": "market" if model == "market" else "limit",
        "smt": bool(smt),
        # features (for analysis and the future ML filter)
        "atr": round(a, 3),
        "risk_atr": round(risk / a, 3),
        "zone_size_atr": round((top - bottom) / a, 3),
        "displacement_atr": round((c[i] - s.ext) * d / a, 3),
        "choch_body_atr": round(abs(c[i] - o[i]) / a, 3),
        "bars_sweep_to_choch": i - s.start,
        "htf_bias": int(bias[i]),
        "ny_hour": int(sess["ny_hour"].iat[i]),
    }
