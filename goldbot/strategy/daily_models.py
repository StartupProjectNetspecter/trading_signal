"""v2 research: time-based models that can trigger every trading day.

Silver Bullet (ICT): inside fixed one-hour New York windows, a displacement candle leaves a Fair
Value Gap in the higher-timeframe trend direction -> limit order in the gap.
    optional: the move must first sweep the low/high formed in the hour before the window.

Opening Range (ORB): mark the high/low of the first minutes after a New York open (COMEX gold
08:20 or stocks 09:30). The first M5 close outside the range in the trend direction -> limit order
on the retest of the broken edge.

Signals use the same fields as asian_sweep.py, so the backtest engine and Telegram code work
unchanged. Everything is computed from closed bars only.
"""
import numpy as np
import pandas as pd

from goldbot.smc.indicators import atr, to_np
from goldbot.smc.sessions import in_window, session_frame
from goldbot.strategy.asian_sweep import BAR, htf_bias


def _minute_of_day(index):
    ny = index.tz_convert("America/New_York")
    return (ny.hour * 60 + ny.minute).to_numpy(), ny


def _signal(model, window, d, i, entry, sl, a, st, close_time, bias, ny_hour, expiry_bars, extra):
    risk = (entry - sl) * d
    if risk < st["min_risk_usd"] or risk > st["max_risk_atr"] * a:
        return None
    rr = st["rr"]
    return {
        "signal_time": close_time[i],
        "expiry_time": close_time[i] + expiry_bars * BAR,
        "direction": "BUY" if d == 1 else "SELL",
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "tp": round(entry + d * rr * risk, 2),
        "rr": rr,
        "session": window,
        "liquidity": model,
        "entry_model": model,
        "order": "limit",
        "model": model,
        "smt": False,
        "atr": round(a, 3),
        "risk_atr": round(risk / a, 3),
        "htf_bias": int(bias[i]),
        "ny_hour": int(ny_hour[i]),
        **extra,
    }


def silver_bullet(m5, cfg, bias=None, sess=None):
    st = cfg["strategy"]
    sb = st["silver_bullet"]
    o, h, l, c = to_np(m5)
    a_ = atr(m5, st["atr_period"]).to_numpy()
    sess = session_frame(m5.index, cfg) if sess is None else sess
    bias = htf_bias(m5, cfg) if bias is None else bias
    news = sess["news_block"].to_numpy()
    minute, ny = _minute_of_day(m5.index)
    ny_hour = ny.hour.to_numpy()
    close_time = m5.index + BAR
    day = sess["session_day"].to_numpy()
    out = []
    for w in sb["windows"]:
        name = f"SB {w[0]}"
        inside = in_window(minute, w)
        # group consecutive window bars (one block per day)
        starts = np.flatnonzero(inside & ~np.r_[False, inside[:-1]])
        for s0 in starts:
            e0 = s0
            while e0 < len(m5) and inside[e0] and day[e0] == day[s0]:
                e0 += 1
            if pd.Timestamp(day[s0]).weekday() >= 5:
                continue
            pre = slice(max(0, s0 - sb["pre_window_bars"]), s0)  # liquidity formed before the window
            pre_lo, pre_hi = (l[pre].min(), h[pre].max()) if s0 > 0 else (np.nan, np.nan)
            for i in range(max(s0, 2), e0):
                a = a_[i]
                if np.isnan(a) or news[i]:
                    continue
                for d in (1, -1):
                    if st["htf_bias"] != "none" and bias[i] != d:
                        continue
                    gap_lo, gap_hi = (h[i - 2], l[i]) if d == 1 else (h[i], l[i - 2])
                    if gap_hi - gap_lo < sb["min_fvg_atr"] * a:
                        continue
                    if abs(c[i - 1] - o[i - 1]) < sb["min_displacement_atr"] * a or (c[i - 1] - o[i - 1]) * d <= 0:
                        continue
                    leg = slice(max(s0 - 3, 0), i + 1)
                    if sb["require_sweep"]:
                        swept = l[leg].min() < pre_lo if d == 1 else h[leg].max() > pre_hi
                        if not swept:
                            continue
                    entry = (gap_lo + gap_hi) / 2 if st["entry_price"] == "ce" else (gap_hi if d == 1 else gap_lo)
                    ext = min(l[i - 2], l[i - 1]) if d == 1 else max(h[i - 2], h[i - 1])
                    if sb["sl_at"] == "leg":
                        ext = l[leg].min() if d == 1 else h[leg].max()
                    sl = ext - d * st["sl_buffer_atr"] * a
                    expiry = max(e0 - i - 1, 1) + sb["expiry_after_window_bars"]
                    sig = _signal("silver_bullet", name, d, i, entry, sl, a, st, close_time, bias, ny_hour, expiry,
                                  {"zone_size_atr": round((gap_hi - gap_lo) / a, 3)})
                    if sig:
                        out.append(sig)
                        break
                else:
                    continue
                break  # one signal per window
    return out


def opening_range(m5, cfg, bias=None, sess=None):
    st = cfg["strategy"]
    orb = st["opening_range"]
    o, h, l, c = to_np(m5)
    a_ = atr(m5, st["atr_period"]).to_numpy()
    sess = session_frame(m5.index, cfg) if sess is None else sess
    bias = htf_bias(m5, cfg) if bias is None else bias
    news = sess["news_block"].to_numpy()
    minute, ny = _minute_of_day(m5.index)
    ny_hour = ny.hour.to_numpy()
    close_time = m5.index + BAR
    day = sess["session_day"].to_numpy()
    rng_mask = in_window(minute, orb["range"])
    trade_mask = in_window(minute, [orb["range"][1], orb["trade_until"]])
    out = []
    for dval in np.unique(day[rng_mask]):
        if pd.Timestamp(dval).weekday() >= 5:
            continue
        r = np.flatnonzero(rng_mask & (day == dval))
        t = np.flatnonzero(trade_mask & (day == dval))
        if len(r) < 2 or not len(t):
            continue
        hi, lo = h[r].max(), l[r].min()
        a = a_[r[-1]]
        if np.isnan(a) or (hi - lo) > orb["max_range_atr"] * a:
            continue
        for i in t:
            if news[i]:
                continue
            d = 1 if c[i] > hi else -1 if c[i] < lo else 0
            if d == 0:
                continue
            if st["htf_bias"] != "none" and bias[i] != d:
                break  # first breakout went against the trend: no trade today
            entry = hi if d == 1 else lo
            if orb["entry"] == "mid_retest":
                entry = (hi + lo) / 2 + d * (hi - lo) / 4
            sl_ref = (hi + lo) / 2 if orb["sl"] == "mid" else (lo if d == 1 else hi)
            sl = sl_ref - d * st["sl_buffer_atr"] * a
            sig = _signal("orb", f"ORB {orb['range'][0]}", d, i, entry, sl, a, st, close_time, bias, ny_hour,
                          orb["expiry_bars"], {"zone_size_atr": round((hi - lo) / a, 3)})
            if sig:
                out.append(sig)
            break
    return out


def generate_daily(m5, cfg):
    st = cfg["strategy"]
    sess = session_frame(m5.index, cfg)
    bias = htf_bias(m5, cfg)
    sigs = []
    if "silver_bullet" in st.get("daily_models", []):
        sigs += silver_bullet(m5, cfg, bias, sess)
    if "opening_range" in st.get("daily_models", []):
        sigs += opening_range(m5, cfg, bias, sess)
    out = pd.DataFrame(sigs)
    if len(out):
        out = out.sort_values("signal_time", kind="stable").reset_index(drop=True)
    return out
