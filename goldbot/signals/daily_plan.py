"""Daily market plan: sent once per trading day before the New York session."""
import json

import pandas as pd

from goldbot.config import resolve
from goldbot.smc.sessions import NY, news_events
from goldbot.signals.status import market_status

STATE = resolve("data/daily_plan_state.json")
WINDOWS = [  # (label, NY start, NY end)
    ("Smart Reversal", "07:00", "10:00"),
    ("NY Breakout (range 08:30–09:00)", "09:00", "12:30"),
    ("Trend Bounce", "08:00", "15:00"),
    ("Dip Buy (⚡ More Trades mode, Tue-Fri)", "18:05", "18:10"),
]


def _ny_day(now):
    return now.tz_convert(NY).normalize()


def plan_text(bars, smt, cfg, tick, active):
    tz = cfg["live"].get("display_tz", "Asia/Phnom_Penh")
    now = pd.Timestamp.now(tz="UTC")
    day = _ny_day(now)
    if day.weekday() >= 5:
        day += pd.Timedelta(days=7 - day.weekday())  # weekend -> plan for Monday
    lines = [f"🗓 Daily plan for {day:%A %d %b} (times in your local time)"]
    lines.append("\nSignal windows today:")
    for label, a, b in WINDOWS:
        start = (day + pd.Timedelta(a + ":00")).tz_convert(tz)
        end = (day + pd.Timedelta(b + ":00")).tz_convert(tz)
        lines.append(f"  • {start:%H:%M}–{end:%H:%M}  {label}")
    after = pd.Timedelta(minutes=cfg["news"]["block_after_min"])
    before = pd.Timedelta(minutes=cfg["news"]["block_before_min"])
    events = [(t, n) for t, n in news_events(cfg, pd.DatetimeIndex([day.tz_convert("UTC"), (day + pd.Timedelta(days=1)).tz_convert("UTC")]))
              if day <= t.tz_convert(NY) < day + pd.Timedelta(days=1)]
    if events:
        lines.append("\n📰 News today (no signals during the block):")
        for t, n in sorted(events):
            lines.append(f"  • {n} {t.tz_convert(tz):%H:%M}  (blocked {(t - before).tz_convert(tz):%H:%M}–{(t + after).tz_convert(tz):%H:%M})")
    else:
        lines.append("\n📰 No major US news today.")
    lines.append("\n" + market_status(bars, smt, cfg, tick, active))
    lines.append("\nPlan: wait for the bot. No setup = no trade. Risk max 0.5–1% per trade.")
    return "\n".join(lines)


def due(cfg):
    """True once per weekday after the configured local time."""
    tz = cfg["live"].get("display_tz", "Asia/Phnom_Penh")
    at = cfg["live"].get("daily_plan_time", "17:30")
    if not at:
        return False
    now = pd.Timestamp.now(tz=tz)
    if _ny_day(now.tz_convert("UTC")).weekday() >= 5 or now.strftime("%H:%M") < at:
        return False
    try:
        last = json.loads(STATE.read_text()).get("last")
    except (FileNotFoundError, ValueError):
        last = None
    return last != now.strftime("%Y-%m-%d")


def mark_sent(cfg):
    tz = cfg["live"].get("display_tz", "Asia/Phnom_Penh")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"last": pd.Timestamp.now(tz=tz).strftime("%Y-%m-%d")}))
