"""Daily market plan: sent once per trading day before the New York session."""
import json

import pandas as pd

from goldbot.config import resolve
from goldbot.smc.sessions import NY, news_events
from goldbot.signals.names import MODES, get_mode, name
from goldbot.signals.status import market_status

STATE = resolve("data/daily_plan_state.json")
WINDOWS = [  # (model, NY start, NY end or None)
    ("v1", "07:00", "10:00"),
    ("v2b", "08:00", "15:00"),
    ("v2a", "09:00", "12:30"),
    ("v3", "18:05", None),
]


def _ny_day(now):
    return now.tz_convert(NY).normalize()


def plan_text(bars, smt, cfg, tick, active):
    """Short daily plan: today's windows for the current mode, news, trend and price."""
    tz = cfg["live"].get("display_tz", "Asia/Phnom_Penh")
    now = pd.Timestamp.now(tz="UTC")
    day = _ny_day(now)
    if day.weekday() >= 5:
        day += pd.Timedelta(days=7 - day.weekday())  # weekend -> plan for Monday
    models = MODES[get_mode(cfg)]["models"]
    lines = [f"🗓 {day:%a %d %b} plan · {MODES[get_mode(cfg)]['label']}"]
    for model, a, b in WINDOWS:
        if model not in models:
            continue
        start = (day + pd.Timedelta(a + ":00")).tz_convert(tz)
        when = f"{start:%H:%M}" if b is None else f"{start:%H:%M}–{(day + pd.Timedelta(b + ':00')).tz_convert(tz):%H:%M}"
        lines.append(f"{when} {name(model)}")
    after = pd.Timedelta(minutes=cfg["news"]["block_after_min"])
    before = pd.Timedelta(minutes=cfg["news"]["block_before_min"])
    events = sorted((t, n) for t, n in news_events(cfg, pd.DatetimeIndex([day.tz_convert("UTC"), (day + pd.Timedelta(days=1)).tz_convert("UTC")]))
                    if day <= t.tz_convert(NY) < day + pd.Timedelta(days=1))
    if events:
        t0 = events[0][0]
        names_ = ", ".join(dict.fromkeys(n for _, n in events))
        lines.append(f"📰 {t0.tz_convert(tz):%H:%M} {names_} → no trades {(t0 - before).tz_convert(tz):%H:%M}–{(events[-1][0] + after).tz_convert(tz):%H:%M}")
    else:
        lines.append("📰 No big news")
    status = market_status(bars, smt, cfg, tick, active).split("\n")
    lines.append(status[2] + " · " + status[0].replace("📈 ", ""))  # H1 trend · price
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
