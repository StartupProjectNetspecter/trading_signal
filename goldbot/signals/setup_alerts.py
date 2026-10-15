"""Setup alerts: information messages as the day develops (NOT trades).

Asian range set, liquidity sweeps (Asian / London / previous-day levels), H1 trend flips,
NY kill zone open, NY opening range set. Each alert is sent once, only when it just happened.
"""
import json

import numpy as np
import pandas as pd

from goldbot.config import resolve
from goldbot.data.store import resample
from goldbot.smc.indicators import atr
from goldbot.smc.sessions import NY, session_frame
from goldbot.smc.structure import market_structure
from goldbot.smc.swings import last_confirmed, swing_points
from goldbot.strategy.asian_sweep import BAR, _Levels

STATE = resolve("data/setup_alerts_state.json")
NAMES = {"asian": "Asian", "london": "London", "pdh_pdl": "previous-day"}
TAG = "ℹ️"


def _h1_trend(bars):
    h1 = resample(bars, "1h")
    right = pd.DataFrame({"t": h1.index + pd.Timedelta("1h"), "v": market_structure(h1, 2)["trend"].to_numpy()})
    return pd.merge_asof(pd.DataFrame({"t": bars.index + BAR}), right, on="t", direction="backward")["v"].fillna(0).to_numpy()


def trade_plan(d, j, bars, cfg, sh_level, sl_level, atr_):
    """Smart Reversal plan after a sweep at bar j: trigger (CHoCH), entry, SL, TP1/TP2 - same rules as the strategy."""
    st = cfg["strategy"]
    h, l = bars["high"].to_numpy(), bars["low"].to_numpy()
    a = atr_[j]
    trigger = sh_level[j] if d == 1 else sl_level[j]
    if np.isnan(a) or np.isnan(trigger):
        return ""
    extreme = l[j] if d == 1 else h[j]
    sl = extreme - d * st["sl_buffer_atr"] * a
    entry = trigger  # the bot will place the exact entry (order block 50%) when the setup confirms
    risk = (entry - sl) * d
    if risk <= 0:
        return ""
    tp1, tp2 = entry + d * risk, entry + d * st["rr"] * risk
    side = "BUY" if d == 1 else "SELL"
    word = ">" if d == 1 else "<"
    return (f"If confirmed → {side} (close {word} {trigger:.2f})\n"
            f"Entry ~{entry:.2f} · SL ~{sl:.2f}\n"
            f"TP1 ~{tp1:.2f} · TP2 ~{tp2:.2f}\n")


def events(bars, cfg):
    """[(key, bar_index, text)] for today's session day."""
    tz = cfg["live"].get("display_tz", "Asia/Phnom_Penh")
    sess = session_frame(bars.index, cfg)
    news = sess["news_block"].to_numpy()
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
    n_sw = cfg["strategy"]["swing_n"]
    sh, sl_ = swing_points(bars["high"].to_numpy(), bars["low"].to_numpy(), n_sw)
    sh_level, _ = last_confirmed(bars["high"].to_numpy(), sh, n_sw)
    sl_level, _ = last_confirmed(bars["low"].to_numpy(), sl_, n_sw)
    atr_ = atr(bars, cfg["strategy"]["atr_period"]).to_numpy()
    out = []
    local = lambda i: (bars.index[i] + BAR).tz_convert(tz)  # noqa: E731
    bias = {1: "🟢 Bullish", -1: "🔴 Bearish", 0: "⚪ Neutral"}

    if day in lv.asian.index:
        r = lv.asian.loc[day]
        j = int(r["end_pos"]) + 1
        if j < n:
            out.append((f"{day:%Y%m%d}_asian", j, f"🌏 Asian range: H {r['asian_high']:.2f} · L {r['asian_low']:.2f}"))
    levels = lv.for_day(day, ds, ["asian", "london", "pdh_pdl"])
    for (name, d), (price, avail) in levels.items():
        if np.isnan(price) or avail >= n:
            continue
        j = lv.first_breach(price, d, avail, n)
        if j < 0:
            continue
        side = "low" if d == 1 else "high"
        head = f"💧 Swept {NAMES[name]} {side} {price:.2f} (now {c[j]:.2f})"
        if news[j]:
            text = head + "\n📰 During news - ignore"
        elif trend[j] != d:
            text = head + "\nAgainst H1 trend - no trade"
        else:
            text = head + "\n" + trade_plan(d, j, bars, cfg, sh_level, sl_level, atr_) + "⚠️ Not a trade yet - wait for the signal"
        out.append((f"{day:%Y%m%d}_sweep_{name}_{d}", j, text))
    for j in range(max(ds, 1), n):
        if trend[j] != trend[j - 1] and trend[j] != 0:
            out.append((f"{bars.index[j]:%Y%m%d%H%M}_h1", j, f"🔄 H1 trend: {bias[int(trend[j])]}"))
        if minute[j] == 420:
            out.append((f"{day:%Y%m%d}_kz", j, f"⏰ NY session open till {local(j) + pd.Timedelta(hours=3) - BAR:%H:%M} · H1 {bias[int(trend[j])]}"))
        if minute[j] == 540:
            rng = np.flatnonzero((minute >= 510) & (minute < 540) & (np.arange(n) >= ds) & (np.arange(n) < j))
            if len(rng) == 6:
                hi, lo = bars["high"].to_numpy()[rng].max(), bars["low"].to_numpy()[rng].min()
                out.append((f"{day:%Y%m%d}_orb", j, f"📏 NY range: H {hi:.2f} · L {lo:.2f}"))
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
        msgs.append(f"{TAG} {text}")
        sent.add(key)
    if msgs:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(sorted(sent)[-300:]))
    return msgs
