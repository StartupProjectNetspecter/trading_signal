"""v2 research: multi-timeframe confluence model (H1 -> M15 -> M5).

  H1  : trend (BOS/CHoCH), dealing range (premium/discount), liquidity target (last H1 swing)
  M15 : points of interest = order blocks and fair value gaps in the H1 direction
  M5  : entry trigger = price taps the M15 zone, then an M5 candle closes beyond the last M5
        swing (CHoCH). SL beyond the tap extreme.

Every trigger becomes a CANDIDATE with confluence factors; research decides which factor
combinations are worth trading. Every value is known at the M5 bar close (no look-ahead).
"""
import numpy as np
import pandas as pd

from goldbot.data.store import resample
from goldbot.smc.fvg import latest_fvg
from goldbot.smc.indicators import atr, to_np
from goldbot.smc.order_block import find_order_block
from goldbot.smc.sessions import session_frame
from goldbot.smc.structure import market_structure
from goldbot.smc.swings import last_confirmed, swing_points
from goldbot.strategy.asian_sweep import BAR

FACTORS = ["h1_trend", "h1_discount", "m15_ob", "m15_fvg", "sweep", "kill_zone", "displacement", "smt"]


def _align(m5, htf, values, tf):
    """Value of each HTF bar, visible to M5 bars that close after the HTF bar closed."""
    right = pd.DataFrame({"t": htf.index + pd.Timedelta(tf), "v": values})
    left = pd.DataFrame({"t": m5.index + BAR})
    return pd.merge_asof(left, right, on="t", direction="backward")["v"].to_numpy()


def _m15_zones(m5, m15, n_swing):
    """M15 order blocks / FVGs: (active_from_m5_idx, d, bottom, top, kind)."""
    o, h, l, c = to_np(m15)
    ev = market_structure(m15, n_swing)["event"].to_numpy()
    avail = m5.index.searchsorted(m15.index + pd.Timedelta("15min"))
    zones = []
    for k in range(2, len(m15)):
        if l[k] > h[k - 2]:
            zones.append((avail[k], 1, h[k - 2], l[k], "fvg"))
        if h[k] < l[k - 2]:
            zones.append((avail[k], -1, h[k], l[k - 2], "fvg"))
        if ev[k]:
            d = 1 if ev[k].endswith("_UP") else -1
            ob = find_order_block(o, h, l, c, max(k - 10, 0), k, d)
            if ob:
                zones.append((avail[k], d, ob[0], ob[1], "ob"))
    zones.sort(key=lambda z: z[0])
    return zones


def candidates(m5, cfg, smt_df=None):
    p = cfg["strategy"]["mtf"]
    o, h, l, c = to_np(m5)
    a_ = atr(m5, 14).to_numpy()
    n = p["m5_swing_n"]
    sh, sl = swing_points(h, l, n)
    sh_lvl, _ = last_confirmed(h, sh, n)
    sl_lvl, _ = last_confirmed(l, sl, n)
    sess = session_frame(m5.index, cfg)
    kz = (sess["london_kz"] | sess["newyork_kz"]).to_numpy()
    news = sess["news_block"].to_numpy()
    ny_hour = sess["ny_hour"].to_numpy()
    close_time = m5.index + BAR

    h1 = resample(m5, "1h")
    h1_trend = _align(m5, h1, market_structure(h1, 2)["trend"].to_numpy(), "1h")
    h1h, h1l = h1["high"].to_numpy(), h1["low"].to_numpy()
    s_hi, s_lo = swing_points(h1h, h1l, 2)
    h1_sh = _align(m5, h1, last_confirmed(h1h, s_hi, 2)[0], "1h")
    h1_sl = _align(m5, h1, last_confirmed(h1l, s_lo, 2)[0], "1h")

    silver_l = silver_h = None
    if smt_df is not None:
        sv = smt_df.reindex(m5.index).ffill()
        silver_h, silver_l = sv["high"].to_numpy(), sv["low"].to_numpy()

    zones = _m15_zones(m5, resample(m5, "15min"), p["m15_swing_n"])
    zi = 0
    active = {1: [], -1: []}
    out = []
    for i in range(len(m5)):
        while zi < len(zones) and zones[zi][0] <= i:
            _, d, bot, top, kind = zones[zi]
            active[d].append({"d": d, "bot": bot, "top": top, "kind": kind, "born": i, "tap": -1})
            zi += 1
        a = a_[i]
        if np.isnan(a):
            continue
        for d in (1, -1):
            keep, fired = [], False
            for z in active[d]:
                if i - z["born"] > p["zone_max_age_bars"]:
                    continue
                if (z["bot"] - c[i] if d == 1 else c[i] - z["top"]) > p["zone_break_atr"] * a:
                    continue  # zone broken
                if z["tap"] < 0:
                    touched = l[i] <= z["top"] if d == 1 else h[i] >= z["bot"]
                    if touched and i > z["born"]:
                        z["tap"], z["ext"], z["ext_idx"] = i, (l[i] if d == 1 else h[i]), i
                        z["choch"] = sh_lvl[i] if d == 1 else sl_lvl[i]
                        z["prior_swing"] = sl_lvl[i - 1] if d == 1 else sh_lvl[i - 1]
                    keep.append(z)
                    continue
                if (l[i] if d == 1 else h[i]) * d < z["ext"] * d:
                    z["ext"], z["ext_idx"] = (l[i] if d == 1 else h[i]), i
                if i - z["tap"] > p["max_bars_tap_to_choch"]:
                    continue
                if np.isnan(z["choch"]) or not ((c[i] - z["choch"]) * d > 0):
                    keep.append(z)
                    continue
                # --- trigger (one per bar per direction)
                if not fired and not news[i]:
                    cand = _candidate(z, d, i, o, h, l, c, a, h1_trend, h1_sh, h1_sl, kz, silver_l, silver_h,
                                      close_time, ny_hour, p)
                    if cand:
                        out.append(cand)
                        fired = True
            active[d] = keep
    return pd.DataFrame(out)


def _candidate(z, d, i, o, h, l, c, a, h1_trend, h1_sh, h1_sl, kz, silver_l, silver_h, close_time, ny_hour, p):
    ext, ext_idx = z["ext"], z["ext_idx"]
    sl = ext - d * p["sl_buffer_atr"] * a
    # M5 entry zone from the reaction leg (FVG, else order block), 50% level
    f = latest_fvg(h, l, ext_idx + 2, i, d, 0.05 * a)
    zone = f[:2] if f else (find_order_block(o, h, l, c, max(ext_idx - 3, 0), i, d) or (None, None))[:2]
    limit = (zone[0] + zone[1]) / 2 if zone[0] is not None else np.nan
    if not np.isnan(limit) and (limit - c[i]) * d >= 0:
        limit = np.nan
    mid = (h1_sh[i] + h1_sl[i]) / 2
    target = h1_sh[i] if d == 1 else h1_sl[i]
    smt = False
    if silver_l is not None:
        seg = slice(max(ext_idx - 24, 0), ext_idx)
        cur = silver_l[ext_idx] if d == 1 else silver_h[ext_idx]
        prev = np.nanmin(silver_l[seg]) if d == 1 else np.nanmax(silver_h[seg])
        smt = bool((cur - prev) * d > 0) and bool((ext - (np.min(l[seg]) if d == 1 else np.max(h[seg]))) * d < 0)
    return {
        "signal_time": close_time[i],
        "d": d,
        "direction": "BUY" if d == 1 else "SELL",
        "market": c[i],
        "limit": limit,
        "sl": sl,
        "atr": a,
        "h1_target": target,
        "ny_hour": int(ny_hour[i]),
        "h1_trend": bool(h1_trend[i] == d),
        "h1_discount": bool(not np.isnan(mid) and (c[i] - mid) * d < 0),
        "m15_ob": z["kind"] == "ob",
        "m15_fvg": z["kind"] == "fvg",
        "sweep": bool(not np.isnan(z["prior_swing"]) and (ext - z["prior_swing"]) * d < 0),
        "kill_zone": bool(kz[i]),
        "displacement": bool(abs(c[i] - o[i]) >= p["displacement_atr"] * a and (c[i] - o[i]) * d > 0),
        "smt": smt,
    }


def to_signals(cands, entry, rr, tp_mode="rr", min_rr=1.0, expiry_bars=12, min_risk=1.0, max_risk_atr=4.0):
    """Turn candidates into engine signals for one entry type / target setting."""
    if cands.empty:
        return cands
    df = cands.copy()
    df["entry"] = df["market"] if entry == "market" else df["limit"]
    df = df[df["entry"].notna()]
    risk = (df["entry"] - df["sl"]) * df["d"]
    df = df[(risk >= min_risk) & (risk <= max_risk_atr * df["atr"])]
    risk = (df["entry"] - df["sl"]) * df["d"]
    if tp_mode == "h1":
        df["rr"] = (df["h1_target"] - df["entry"]) * df["d"] / risk
        df = df[df["rr"] >= min_rr]
        df["tp"] = df["h1_target"]
    else:
        df["rr"] = rr
        df["tp"] = df["entry"] + df["d"] * rr * risk
    df["order"] = entry if entry == "market" else "limit"
    df["expiry_time"] = df["signal_time"] + expiry_bars * BAR
    df["entry_model"], df["session"], df["liquidity"] = "mtf", "mtf", "m15_poi"
    return df.reset_index(drop=True)
