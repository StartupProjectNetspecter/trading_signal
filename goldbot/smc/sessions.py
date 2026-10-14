"""ICT sessions, kill zones and news blackout, defined in New York time (DST-safe).

A "session day" starts at 18:00 New York (the gold daily open), so the Asian range
from the evening before belongs to the next day's London / New York kill zones.
"""
import numpy as np
import pandas as pd

from goldbot.config import resolve

NY = "America/New_York"


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_window(minute_of_day, window):
    start, end = _minutes(window[0]), _minutes(window[1])
    if start < end:
        return (minute_of_day >= start) & (minute_of_day < end)
    return (minute_of_day >= start) | (minute_of_day < end)  # wraps midnight, e.g. 20:00-00:00


def session_frame(index, cfg):
    """Per-bar session info for a UTC DatetimeIndex of bar OPEN times."""
    ny = index.tz_convert(NY)
    minute = (ny.hour * 60 + ny.minute).to_numpy()
    s = cfg["sessions"]
    out = pd.DataFrame(index=index)
    out["session_day"] = (ny + pd.Timedelta(hours=6)).normalize().tz_localize(None)
    out["ny_hour"] = ny.hour
    out["asian"] = in_window(minute, s["asian_range"])
    out["london_kz"] = in_window(minute, s["london_kz"])
    out["newyork_kz"] = in_window(minute, s["newyork_kz"])
    out["news_block"] = news_mask(index, cfg)
    return out


def news_events(cfg, index):
    """[(utc_time, name)] for all blocked news events covering the span of `index`."""
    n = cfg["news"]
    events = [(t, "NFP") for t in _nfp_times(index)] if n.get("block_nfp") else []
    path = resolve(n["events_file"]) if n.get("events_file") else None
    if path is not None and path.exists():
        ev = pd.read_csv(path)
        events += list(zip(pd.to_datetime(ev["datetime_utc"], utc=True), ev["event"]))
    return events


def news_mask(index, cfg):
    n = cfg["news"]
    before, after = pd.Timedelta(minutes=n["block_before_min"]), pd.Timedelta(minutes=n["block_after_min"])
    mask = np.zeros(len(index), dtype=bool)
    for t, _ in news_events(cfg, index):
        mask |= (index >= t - before) & (index < t + after)
    return mask


def _nfp_times(index):
    """Approximation: Non-Farm Payrolls = first Friday of each month, 08:30 New York."""
    if len(index) == 0:
        return []
    first_ny, last_ny = (t.tz_convert(NY).tz_localize(None) for t in (index[0], index[-1]))
    months = pd.period_range(first_ny.to_period("M"), last_ny.to_period("M"))
    times = []
    for m in months:
        first = m.to_timestamp()
        friday = first + pd.Timedelta(days=(4 - first.weekday()) % 7)
        times.append((friday + pd.Timedelta(hours=8, minutes=30)).tz_localize(NY).tz_convert("UTC"))
    return times
