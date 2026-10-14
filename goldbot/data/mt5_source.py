"""Candles from your MetaTrader 5 terminal (must be running and logged in)."""
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:  # allows backtesting on machines without MT5
    mt5 = None

TIMEFRAMES = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "H1": "TIMEFRAME_H1"}


def connect(symbol):
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package not installed")
    if not mt5.initialize():
        raise RuntimeError(
            f"MT5 initialize failed: {mt5.last_error()}. Open MetaTrader 5 and log in to your (demo) account."
        )
    if not mt5.symbol_select(symbol, True):
        names = [s.name for s in mt5.symbols_get() if "XAU" in s.name or "GOLD" in s.name.upper()]
        raise RuntimeError(f"Symbol {symbol!r} not found. Gold symbols on this broker: {names}")


def shutdown():
    if mt5 is not None:
        mt5.shutdown()


def detect_server_offset_hours(symbol):
    """Broker server time minus UTC, in whole hours, measured from the latest tick."""
    # the symbol itself may not have ticked yet: fall back to any visible symbol with a fresh tick
    candidates = [symbol] + [s.name for s in mt5.symbols_get() if s.visible]
    times = [t.time for t in map(mt5.symbol_info_tick, candidates) if t is not None and t.time]
    if not times:
        raise RuntimeError("No tick received; cannot detect server time offset")
    return round((max(times) - time.time()) / 3600)


def _ny_plus_7_now():
    ny = pd.Timestamp.now(tz="America/New_York")
    return round(ny.utcoffset().total_seconds() / 3600) + 7


def _to_utc(epoch_seconds, server_tz):
    """MT5 returns server wall-clock time encoded as epoch seconds. Convert it to real UTC."""
    naive = pd.DatetimeIndex(pd.to_datetime(epoch_seconds, unit="s"))
    if server_tz == "ny+7":  # most brokers: server midnight = 17:00 New York (UTC+2 winter / UTC+3 summer)
        ny = (naive - pd.Timedelta(hours=7)).tz_localize(
            "America/New_York", ambiguous="NaT", nonexistent="shift_forward"
        )
        return ny.tz_convert("UTC")
    return (naive - pd.Timedelta(hours=int(server_tz))).tz_localize("UTC")


def resolve_server_tz(symbol, setting):
    if setting != "auto":
        return setting
    offset = detect_server_offset_hours(symbol)
    return "ny+7" if offset == _ny_plus_7_now() else offset


def _frame(rates, server_tz):
    df = pd.DataFrame(rates)
    df.index = _to_utc(df["time"], server_tz)
    df.index.name = "time"
    df = df.rename(columns={"tick_volume": "volume"})[["open", "high", "low", "close", "volume"]]
    df = df[df.index.notna()]
    return df[~df.index.duplicated()].sort_index()


def download(symbol, timeframe, start, end, server_tz="auto"):
    """Download history in monthly chunks (avoids terminal bar limits)."""
    tz = resolve_server_tz(symbol, server_tz)
    tf = getattr(mt5, TIMEFRAMES[timeframe])
    frames = []
    cur = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    stop = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1)
    while cur < stop:
        nxt = min(cur + timedelta(days=31), stop)
        rates = mt5.copy_rates_range(symbol, tf, cur, nxt)
        if rates is not None and len(rates):
            frames.append(_frame(rates, tz))
        cur = nxt
    if not frames:
        raise RuntimeError(f"MT5 returned no {timeframe} data: {mt5.last_error()}")
    out = pd.concat(frames).sort_index()
    return out[~out.index.duplicated()], tz


def latest_closed_bars(symbol, timeframe, count, server_tz):
    """Most recent `count` CLOSED bars (the still-forming bar is dropped)."""
    rates = mt5.copy_rates_from_pos(symbol, getattr(mt5, TIMEFRAMES[timeframe]), 0, count + 1)
    if rates is None or len(rates) < 2:
        raise RuntimeError(f"MT5 returned no recent data: {mt5.last_error()}")
    return _frame(rates, server_tz).iloc[:-1]
