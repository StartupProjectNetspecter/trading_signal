"""Free historical M1 candles from Dukascopy (UTC, BID prices).

Each trading day is one LZMA-compressed .bi5 file of 24-byte records:
    seconds_from_midnight, open, close, low, high (int32, price * divisor), volume (float32)
Raw files are cached under data/raw so re-running only downloads missing days.
"""
import lzma
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

URL = "https://datafeed.dukascopy.com/datafeed/{inst}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
RECORD = np.dtype([("t", ">i4"), ("o", ">i4"), ("c", ">i4"), ("l", ">i4"), ("h", ">i4"), ("v", ">f4")])


def _fetch_day(inst, day, cache_dir):
    path = Path(cache_dir) / f"{day:%Y}" / f"{day:%Y-%m-%d}.bi5"
    if path.exists():
        return day, path.read_bytes()
    url = URL.format(inst=inst, y=day.year, m=day.month - 1, d=day.day)  # month is 0-based
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=30).read()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            time.sleep(0.3)  # be polite: Dukascopy drops connections when hammered
            return day, raw
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return day, b""
            time.sleep(5 * 2**attempt)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(5 * 2**attempt)
    print(f"  WARNING: skipped {day} (download failed, re-run later to fill the gap)")
    return day, None


def _parse_day(day, raw, divisor):
    if not raw:
        return None
    rec = np.frombuffer(lzma.decompress(raw), dtype=RECORD)
    rec = rec[rec["v"] > 0]  # closed-market minutes are flat with zero volume
    if len(rec) == 0:
        return None
    idx = pd.Timestamp(day, tz="UTC") + pd.to_timedelta(rec["t"], unit="s")
    return pd.DataFrame(
        {
            "open": rec["o"] / divisor,
            "high": rec["h"] / divisor,
            "low": rec["l"] / divisor,
            "close": rec["c"] / divisor,
            "volume": rec["v"].astype(float),
        },
        index=idx,
    )


def download_m1(inst, start, end, cache_dir, divisor=1000, workers=1):
    """Download M1 candles for [start, end] (dates, UTC). Returns a UTC-indexed DataFrame."""
    days = []
    d = start
    while d <= end:
        if d.weekday() != 5:  # Saturday never trades
            days.append(d)
        d += timedelta(days=1)

    frames = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, (day, raw) in enumerate(pool.map(lambda x: _fetch_day(inst, x, cache_dir), days), 1):
            df = _parse_day(day, raw, divisor)
            if df is not None:
                frames.append(df)
            if n % 50 == 0 or n == len(days):
                print(f"  dukascopy: {n}/{len(days)} days")
    if not frames:
        raise RuntimeError("No data downloaded from Dukascopy")
    out = pd.concat(frames).sort_index()
    out.index.name = "time"
    return out[~out.index.duplicated()]


def default_end():
    return date.today() - timedelta(days=1)
