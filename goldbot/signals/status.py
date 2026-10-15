"""Human-readable market status for the Telegram buttons (price, session, bias, liquidity, news)."""
import numpy as np
import pandas as pd

from goldbot.smc.sessions import NY, _minutes, news_events, session_frame
from goldbot.strategy.asian_sweep import _Levels, htf_bias

LEVEL_NAMES = {"asian": "Asian", "london": "London", "pdh_pdl": "Prev. day"}


def _local(t, cfg):
    return t.tz_convert(cfg["live"].get("display_tz", "Asia/Phnom_Penh"))


def _fmt_delta(td):
    mins = int(td.total_seconds() // 60)
    return f"{mins // 60}h {mins % 60:02d}m" if mins >= 60 else f"{mins}m"


def kill_zone_info(now, cfg):
    """(is_open, text) for the configured kill zones, using New York time and weekdays only."""
    zones = cfg["strategy"].get("kill_zones", ["london", "newyork"])
    ny_now = now.tz_convert(NY)
    best = None
    for day_offset in range(0, 8):
        d = (ny_now + pd.Timedelta(days=day_offset)).normalize()
        if d.weekday() >= 5:
            continue
        for z in zones:
            w = cfg["sessions"][f"{z}_kz"]
            start = d + pd.Timedelta(minutes=_minutes(w[0]))
            end = d + pd.Timedelta(minutes=_minutes(w[1]))
            if start <= ny_now < end:
                return True, f"🟢 NY session open till {_local(end, cfg):%H:%M}"
            if start > ny_now and (best is None or start < best[0]):
                best = (start, z)
        if best:
            break
    start, z = best
    return False, f"⏳ NY session {_local(start, cfg):%a %H:%M} (in {_fmt_delta(start - ny_now)})"


def market_status(bars, smt, cfg, tick=None, active=None):
    """Short status: price, session, H1 trend, today's levels, next news, active signal."""
    now = pd.Timestamp.now(tz="UTC")
    price = tick[0] if tick else bars["close"].iat[-1]
    lines = [f"📈 {cfg['symbol']} {price:.2f}", kill_zone_info(now, cfg)[1]]
    bias = int(htf_bias(bars, cfg)[-1])
    lines.append({1: "H1: 🟢 Bullish (BUY only)", -1: "H1: 🔴 Bearish (SELL only)", 0: "H1: ⚪ Neutral (no trades)"}[bias])

    sess = session_frame(bars.index, cfg)
    levels = _Levels(bars, sess)
    day = pd.Timestamp(sess["session_day"].iat[-1])
    ds = int(np.flatnonzero(sess["session_day"].to_numpy() == sess["session_day"].iat[-1])[0])
    lv = levels.for_day(day, ds, cfg["strategy"].get("liquidity_levels", ["asian"]))
    for name in ("asian", "london"):
        parts = []
        for d, side in ((-1, "H"), (1, "L")):
            if (name, d) not in lv:
                continue
            price_lv, avail = lv[(name, d)]
            if np.isnan(price_lv) or avail >= len(bars):
                continue
            swept = levels.first_breach(price_lv, d, avail, len(bars)) >= 0
            parts.append(f"{side} {price_lv:.2f}{' ✅' if swept else ''}")
        if parts:
            lines.append(f"{LEVEL_NAMES.get(name, name)}: " + " · ".join(parts))

    after = pd.Timedelta(minutes=cfg["news"]["block_after_min"])
    upcoming = sorted((t, n) for t, n in news_events(cfg, pd.DatetimeIndex([now, now + pd.Timedelta(days=40)])) if t + after > now)
    if upcoming:
        t, n = upcoming[0]
        lines.append(f"📰 {n} {_local(t, cfg):%a %d %b %H:%M}")
    if active:
        lines.append(f"Signal: {active['direction']} @ {active['entry']:.2f} (till {_local(active['expiry_time'], cfg):%H:%M})")
    else:
        lines.append("Signal: none")
    return "\n".join(lines)
