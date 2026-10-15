"""Setup alerts: information messages as the day develops (NOT trades).

Asian range set, liquidity sweeps (Asian / London / previous-day levels), H1 trend flips,
NY kill zone open, NY opening range set. Each alert is sent once, only when it just happened.
"""
import json

import numpy as np
import pandas as pd

from goldbot.config import resolve
from goldbot.data.store import resample
from goldbot.smc.sessions import NY, session_frame
from goldbot.smc.structure import market_structure
from goldbot.strategy.asian_sweep import BAR, _Levels

STATE = resolve("data/setup_alerts_state.json")
NAMES = {"asian": "Asian", "london": "London", "pdh_pdl": "previous-day"}
TAG = "ℹ️ ALERT (not a trade)"


def _h1_trend(bars):
    h1 = resample(bars, "1h")
    right = pd.DataFrame({"t": h1.index + pd.Timedelta("1h"), "v": market_structure(h1, 2)["trend"].to_numpy()})
    return pd.merge_asof(pd.DataFrame({"t": bars.index + BAR}), right, on="t", direction="backward")["v"].fillna(0).to_numpy()


def events(bars, cfg):
    """[(key, bar_index, text)] for today's session day."""
    tz = cfg["live"].get("display_tz", "Asia/Phnom_Penh")
    sess = session_frame(bars.index, cfg)
    day_arr = sess["session_day"].to_numpy()
    day = pd.Timestamp(day_arr[-1])
    if day.weekday() >= 5:
        return []
    ds = int(np.flatnonzero(day_arr == day_arr[-1])[0])
    n = len(bars)
    lv = _Levels(bars, sess)
    trend = _h1_trend(bars)
    ny = bars.index.tz_convert(NY)
    minute = (ny.hour * 60 + ny.minute).to_numpy()
    c = bars["close"].to_numpy()
    out = []
    local = lambda i: (bars.index[i] + BAR).tz_convert(tz)  # noqa: E731
    bias = {1: "BULLISH 🟢 (bot looks for BUY setups)", -1: "BEARISH 🔴 (bot looks for SELL setups)", 0: "NEUTRAL ⚪"}

    if day in lv.asian.index:
        r = lv.asian.loc[day]
        j = int(r["end_pos"]) + 1
        if j < n:
            out.append((f"{day:%Y%m%d}_asian", j, f"🌏 Asian range set: High {r['asian_high']:.2f} / Low {r['asian_low']:.2f} "
                        f"({r['asian_high'] - r['asian_low']:.2f}). Sweeps of these levels in the NY session can lead to a Smart Reversal setup."))
    levels = lv.for_day(day, ds, ["asian", "london", "pdh_pdl"])
    for (name, d), (price, avail) in levels.items():
        if np.isnan(price) or avail >= n:
            continue
        j = lv.first_breach(price, d, avail, n)
        if j < 0:
            continue
        side = "low" if d == 1 else "high"
        maybe = "BUY" if d == 1 else "SELL"
        agree = "✅ agrees with the H1 trend" if trend[j] == d else "⚠️ against the H1 trend (Smart Reversal needs H1 agreement)"
        out.append((f"{day:%Y%m%d}_sweep_{name}_{d}", j,
                    f"💧 Liquidity sweep: price took the {NAMES[name]} {side} {price:.2f} at {local(j):%H:%M} (now {c[j]:.2f}).\n"
                    f"A {maybe} reversal is possible if a CHoCH follows - {agree}.\n"
                    f"A sweep alone reverses only ~48% of the time (coin flip) - wait for a real signal, do not trade this alert."))
    for j in range(max(ds, 1), n):
        if trend[j] != trend[j - 1] and trend[j] != 0:
            out.append((f"{bars.index[j]:%Y%m%d%H%M}_h1", j, f"🔄 H1 trend is now {bias[int(trend[j])]}"))
        if minute[j] == 420:
            out.append((f"{day:%Y%m%d}_kz", j, f"⏰ New York kill zone is open until {local(j) + pd.Timedelta(hours=3) - BAR:%H:%M} - "
                        f"H1 trend {bias[int(trend[j])]}"))
        if minute[j] == 540:
            rng = np.flatnonzero((minute >= 510) & (minute < 540) & (np.arange(n) >= ds) & (np.arange(n) < j))
            if len(rng) == 6:
                hi, lo = bars["high"].to_numpy()[rng].max(), bars["low"].to_numpy()[rng].min()
                out.append((f"{day:%Y%m%d}_orb", j, f"📏 NY opening range set: High {hi:.2f} / Low {lo:.2f}. "
                            f"NY Breakout waits for a close outside it in the H1 trend direction ({bias[int(trend[j])].split(' (')[0]})."))
    return out


def new_alerts(bars, cfg, recent_bars=3):
    """Alerts that happened in the last few closed bars and were not sent before."""
    try:
        sent = set(json.loads(STATE.read_text()))
    except (FileNotFoundError, ValueError):
        sent = set()
    n = len(bars)
    msgs = []
    for key, j, text in sorted(events(bars, cfg), key=lambda e: e[1]):
        if key in sent or j < n - recent_bars:
            continue
        msgs.append(f"{TAG}\n{text}")
        sent.add(key)
    if msgs:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(sorted(sent)[-300:]))
    return msgs
