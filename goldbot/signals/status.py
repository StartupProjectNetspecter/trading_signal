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
                return True, f"🟢 {z.upper()} kill zone OPEN (closes {_local(end, cfg):%H:%M}, in {_fmt_delta(end - ny_now)})"
            if start > ny_now and (best is None or start < best[0]):
                best = (start, z)
        if best:
            break
    start, z = best
    return False, f"⏳ Next {z.upper()} kill zone: {_local(start, cfg):%a %H:%M} (in {_fmt_delta(start - ny_now)})"


def market_status(bars, smt, cfg, tick=None, active=None):
    sym = cfg["symbol"]
    now = pd.Timestamp.now(tz="UTC")
    last = bars.iloc[-1]
    lines = [f"📈 {sym} market status"]
    if tick:
        lines.append(f"Price: {tick[0]:.2f} / {tick[1]:.2f}")
    else:
        lines.append(f"Price: {last['close']:.2f} (last M5 close)")
    lines.append(f"Time: {_local(now, cfg):%H:%M} local · {now.tz_convert(NY):%H:%M} New York")

    _, kz_text = kill_zone_info(now, cfg)
    lines.append(f"Session: {kz_text}")

    bias = int(htf_bias(bars, cfg)[-1])
    tf = cfg["strategy"].get("htf_timeframe", "1h").upper()
    lines.append(
        {1: f"{tf} bias: 🟢 Bullish → looking for BUY setups",
         -1: f"{tf} bias: 🔴 Bearish → looking for SELL setups",
         0: f"{tf} bias: ⚪ Neutral → no trades until structure breaks"}[bias]
    )

    # today's liquidity levels and whether they have been swept
    sess = session_frame(bars.index, cfg)
    levels = _Levels(bars, sess)
    day = pd.Timestamp(sess["session_day"].iat[-1])
    ds = int(np.flatnonzero(sess["session_day"].to_numpy() == sess["session_day"].iat[-1])[0])
    lv = levels.for_day(day, ds, cfg["strategy"].get("liquidity_levels", ["asian"]))
    if lv:
        lines.append("Liquidity today:")
        for (name, d), (price, avail) in sorted(lv.items(), key=lambda kv: -kv[1][0]):
            if np.isnan(price) or avail >= len(bars):
                continue
            side = "low" if d == 1 else "high"
            swept = levels.first_breach(price, d, avail, len(bars)) >= 0
            lines.append(f"  • {LEVEL_NAMES.get(name, name)} {side} {price:.2f} — {'swept ✅' if swept else 'not swept'}")
    else:
        lines.append("Liquidity today: Asian range not complete yet")

    after = pd.Timedelta(minutes=cfg["news"]["block_after_min"])
    upcoming = sorted(
        (t, name) for t, name in news_events(cfg, pd.DatetimeIndex([now, now + pd.Timedelta(days=40)])) if t + after > now
    )
    if upcoming:
        lines.append("Next news blocks (no signals around these):")
        for t, name in upcoming[:4]:
            lines.append(f"  • {name} {_local(t, cfg):%a %d %b %H:%M}")

    if active:
        lines.append(f"Active signal: {active['direction']} @ {active['entry']:.2f} (valid until {_local(active['expiry_time'], cfg):%H:%M})")
    else:
        lines.append("Active signal: none")
    return "\n".join(lines)
