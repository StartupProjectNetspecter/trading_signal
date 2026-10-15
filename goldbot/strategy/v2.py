"""v2 signals: two research-selected setups, ported 1:1 from Codex's verified search engine
(research/search_10k_verify.reference) plus the two filters found in research/v2_improve.py.

  v2a  NY opening range (08:30-09:00 NY), first M5 close outside it in the H1 trend direction,
       limit order on the broken edge (cancelled after 20 min). Filter: ADX >= 20 and volatility ratio >= 1.34
       (ATR above its 1-day average = market moving more than usual). BE at +1R, TP 1.5R.
  v2b  Bollinger(20, 1.5) re-entry candle in the M15 trend direction, market order, stop 3 ATR.
       Filter: ADX >= 30.6 (strong trend), body >= 0.2 ATR, volatility ratio 0.5-1.5.
       Half at +1R then BE, TP 3R.

Every value is known at the signal bar close. `generate_v2` also simulates earlier v2 trades so
the one-position-at-a-time rule (capacity) matches the backtest.
"""
import numpy as np
import pandas as pd

from goldbot.data.store import resample
from goldbot.smc.indicators import atr
from goldbot.smc.sessions import news_mask
from goldbot.smc.structure import market_structure

BAR = pd.Timedelta(minutes=5)
NY = "America/New_York"

MODELS = {
    "v2a": dict(name="V2a Opening range", source="opening_range", start=120, end=900, cap=1, cooldown=24, stop_mode=0,
                buffer=0.3, rr=1.5, min_risk=3.0, max_risk=8.0, expiry=4, hold=8, management=1, bias="h1",
                adx_min=20.0, adx_max=100.0, body=0.0, vol_min=1.34, vol_max=100.0),
    "v2b": dict(name="V2b Bollinger", source="bollinger", start=480, end=900, cap=3, cooldown=12, stop_mode=6,
                buffer=0.75, rr=3.0, min_risk=3.0, max_risk=8.0, expiry=1, hold=4, management=2, bias="m15",
                adx_min=30.61, adx_max=100.0, body=0.2, vol_min=0.5, vol_max=1.5),
}


def _round_cent(x):
    return float(np.rint(x * 100) / 100)  # .NET-style banker's rounding, as in the research engine


def _trend(m5, tf, bars_per):
    htf = resample(m5, tf)
    count = m5["close"].resample(tf).count()
    htf = htf[count.reindex(htf.index) == bars_per]  # complete higher-timeframe candles only
    right = pd.DataFrame({"t": htf.index + pd.Timedelta(tf), "v": market_structure(htf, 2)["trend"].to_numpy()})
    left = pd.DataFrame({"t": m5.index + BAR})
    return pd.merge_asof(left, right, on="t", direction="backward")["v"].fillna(0).to_numpy()


def features(m5, cfg):
    close_local = (m5.index + BAR).tz_convert(NY)
    a = atr(m5, 14)
    up, down = m5["high"].diff(), -m5["low"].diff()
    plus = up.where((up > down) & (up > 0), 0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    minus = down.where((down > up) & (down > 0), 0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    dx = (100 * (plus - minus).abs() / (plus + minus).replace(0, np.nan)).fillna(0)
    return {
        "t": (m5.index.as_unit("ns").asi8 // 10**9).astype(np.int64),
        "o": m5["open"].to_numpy(), "h": m5["high"].to_numpy(), "l": m5["low"].to_numpy(), "c": m5["close"].to_numpy(),
        "atr": a.to_numpy(),
        "adx": dx.ewm(alpha=1 / 14, adjust=False, min_periods=28).mean().to_numpy(),
        "body": ((m5["close"] - m5["open"]).abs() / a).to_numpy(),
        "vol": (a / a.rolling(288, min_periods=288).mean()).to_numpy(),
        "minute": (close_local.hour * 60 + close_local.minute).to_numpy(),
        "day": close_local.tz_localize(None).normalize().as_unit("ns").asi8 // 86_400_000_000_000,
        "wd": close_local.weekday.to_numpy(),
        "news": news_mask(m5.index, cfg) | news_mask(m5.index + BAR, cfg),
        "h1": _trend(m5, "1h", 12),
        "m15": _trend(m5, "15min", 3),
    }


def opening_range_setups(m5, f, begin=510, length=30):
    """Codex source 46: 08:30 NY range of 30 minutes, edge entry."""
    local = m5.index.tz_convert(NY)
    minute = local.hour * 60 + local.minute
    day = local.tz_localize(None).normalize()
    rows = []
    idx = np.arange(len(m5))
    for dval in np.unique(day):
        r = np.flatnonzero((day == dval) & (minute >= begin) & (minute < begin + length))
        if len(r) != length // 5 or not (np.diff(m5.index[r].as_unit("ns").asi8) == BAR.value).all():
            continue
        hi, lo = f["h"][r].max(), f["l"][r].min()
        for i in np.flatnonzero((day == dval) & (idx > r[-1]) & (minute < 750)):
            d = 1 if f["c"][i] > hi else -1 if f["c"][i] < lo else 0
            if d:
                rows.append(dict(i=int(i), d=d, entry=hi if d == 1 else lo, stop_ref=lo if d == 1 else hi, order=1, expiry_bars=12, window=begin))
                break
    return rows


def bollinger_setups(m5, f, length=20, width=1.5):
    """Codex source 33: close back inside Bollinger(20, 1.5) with a candle in that direction."""
    c = m5["close"]
    mid, sd = c.rolling(length).mean(), c.rolling(length).std(ddof=0)
    lo, hi = mid - width * sd, mid + width * sd
    buy = (c.shift(1) < lo.shift(1)) & (c > lo) & (c > m5["open"])
    sell = (c.shift(1) > hi.shift(1)) & (c < hi) & (c < m5["open"])
    low6, high6 = m5["low"].rolling(6).min(), m5["high"].rolling(6).max()
    rows = []
    for d, mask, stop in ((1, buy, low6), (-1, sell, high6)):
        for i in np.flatnonzero(mask.fillna(False).to_numpy()):
            rows.append(dict(i=int(i), d=d, entry=float(c.iat[i]), stop_ref=float(stop.iat[i]), order=0, expiry_bars=1, window=-1))
    return sorted(rows, key=lambda r: (r["i"], r["d"]))


def execute(f, i, d, entry, stop, target, market, expiry_bars, p, spread=0.6, slip=0.1):
    """Follow one v2 order from signal bar i. Returns outcome, fill_i, exit_i, r and `free` (when the slot frees).

    outcome 'pending' / 'open' = not resolved by the end of the data (live)."""
    t, o, h, l, c = f["t"], f["o"], f["h"], f["l"], f["c"]
    n = len(t)
    signal = t[i] + 300
    start = t.searchsorted(signal)
    expiry = signal + 300 * expiry_bars
    fill, px, reason, free = -1, 0.0, "expired", expiry
    for j in range(start, n):
        if t[j] >= expiry:
            break
        if f["news"][j]:
            reason, free = "news_cancel", t[j] + 300
            break
        op = o[j] + (spread if d == -1 else 0)
        if (op - stop) * d <= 0 or (op - target) * d >= 0:
            reason, free = "invalid_gap", t[j] + 300
            break
        if market:
            fill, px = j, o[j] + (spread + slip if d == 1 else -slip)
        elif (l[j] + spread <= entry) if d == 1 else (h[j] >= entry):
            fill, px = j, entry
        if fill >= 0:
            if (px - stop) * d <= 0 or (target - px) * d <= 0:
                fill, reason, free = -1, "invalid_fill", t[j] + 300
            break
        if (h[j] >= target) if d == 1 else (l[j] + spread <= target):
            reason, free = "cancelled", t[j] + 300
            break
    else:
        if t[n - 1] + 300 < expiry:
            return dict(outcome="pending", fill_i=-1, exit_i=-1, r=0.0, free=10**18)
    if fill < 0:
        return dict(outcome=reason, fill_i=-1, exit_i=-1, r=0.0, free=free)
    risk = (px - stop) * d
    deadline = t[fill] + int(p["hold"]) * 3600
    maximum = min(t.searchsorted(deadline) - 1, n - 1)
    active, size, banked, partial = stop, 1.0, 0.0, False
    exit_i, exit_px, outcome = -1, 0.0, "time"
    for j in range(fill, maximum + 1):
        sp = spread if d == -1 else 0
        lo_, hi_, op = l[j] + sp, h[j] + sp, o[j] + sp
        if (lo_ <= active) if d == 1 else (hi_ >= active):
            exit_i = j
            exit_px = (min(active, op) if d == 1 else max(active, op)) - d * slip
            outcome = "sl" if active == stop else "be"
            break
        if j == fill:
            continue
        best, one = (hi_ if d == 1 else lo_), px + d * risk
        if p["management"] == 2 and not partial and (target - one) * d > 0 and (best - one) * d >= 0:
            size, banked, partial = 0.5, 0.5 * risk, True
        if (best - target) * d >= 0:
            exit_i, exit_px, outcome = j, target, "tp"
            break
        be_level = px + d * risk * p.get("be_r", 1.0)  # break-even trigger (default +1R, as researched)
        if p["management"] > 0 and (target - be_level) * d > 0 and (best - be_level) * d >= 0:
            active = px
    if exit_i < 0:
        nxt = maximum + 1
        if maximum == n - 1 and t[maximum] + 300 < deadline:
            return dict(outcome="open", fill_i=fill, exit_i=-1, r=0.0, free=10**18)
        if nxt < n and t[nxt] > deadline and t[maximum] + 300 < deadline:
            exit_i, exit_px, outcome = nxt, o[nxt] + (spread if d == -1 else 0) - d * slip, "time_gap"
        else:
            exit_i, exit_px = maximum, c[maximum] + (spread if d == -1 else 0) - d * slip
    r = (banked + size * (exit_px - px) * d) / risk
    return dict(outcome=outcome + ("+partial" if partial else ""), fill_i=fill, exit_i=exit_i, r=r, free=t[exit_i] + 300)


def run_model(f, rows, p, spread=0.6, slip=0.1):
    """Port of research.search_10k_verify.reference (decision filter + execution for capacity).

    Returns records; outcome 'open' / 'pending' means unresolved at the end of the data (live)."""
    t, a = f["t"], f["atr"]
    last, last_day, count, free = -100000, -1, 0, -10**18
    windows, records = set(), []
    for row in rows:
        i, d = row["i"], row["d"]
        if f["wd"][i] >= 5 or f["news"][i] or not p["start"] <= f["minute"][i] < p["end"] or i - last < p["cooldown"]:
            continue
        if f[p["bias"]][i] != d:
            continue
        adx, vol, body = f["adx"][i], f["vol"][i], f["body"][i]
        if not np.isfinite(adx) or not np.isfinite(vol) or not p["adx_min"] <= adx <= p["adx_max"] or body < p["body"] or not p["vol_min"] <= vol <= p["vol_max"]:
            continue
        if f["day"][i] != last_day:
            last_day, count = f["day"][i], 0
        if count >= p["cap"]:
            continue
        window = (int(f["day"][i]), row["window"])
        if row["window"] >= 0 and window in windows:
            continue
        entry = _round_cent(row["entry"])
        ref = row["stop_ref"] if p["stop_mode"] == 0 else entry - d * p["stop_mode"] * a[i] / 2
        stop = _round_cent(ref - d * p["buffer"] * a[i])
        planned = (entry - stop) * d
        if not np.isfinite(planned) or not np.isfinite(a[i]) or planned < p["min_risk"] or planned > p["max_risk"] * a[i]:
            continue
        target = _round_cent(entry + d * p["rr"] * planned)
        if (target - entry) * d <= 0:
            continue
        last, count = i, count + 1
        if row["window"] >= 0:
            windows.add(window)
        rec = dict(signal_i=i, d=d, entry=entry, sl=stop, tp=target, order="market" if row["order"] == 0 else "limit",
                   expiry_bars=1 if row["order"] == 0 else p["expiry"] or row["expiry_bars"], fill_i=-1, exit_i=-1, r=0.0)
        if t[i] + 300 < free:
            records.append(dict(rec, outcome="capacity"))
            continue
        res = execute(f, i, d, entry, stop, target, row["order"] == 0, rec["expiry_bars"], p, spread, slip)
        free = res.pop("free")
        records.append(dict(rec, **res))
    return pd.DataFrame(records)


def generate_v2(m5, cfg, spread=0.6, slip=0.1):
    """All v2 signals (both models) as signal dicts usable by the Telegram code."""
    f = features(m5, cfg)
    setups = {"opening_range": opening_range_setups(m5, f), "bollinger": bollinger_setups(m5, f)}
    out = []
    for key, p in MODELS.items():
        rec = run_model(f, setups[p["source"]], p, spread, slip)
        if rec.empty:
            continue
        rec = rec[rec["outcome"] != "capacity"]
        for r in rec.to_dict("records"):
            i = r["signal_i"]
            st = m5.index[i] + BAR
            out.append({
                "signal_time": st, "expiry_time": st + r["expiry_bars"] * BAR, "direction": "BUY" if r["d"] == 1 else "SELL",
                "entry": r["entry"], "sl": r["sl"], "tp": r["tp"], "rr": p["rr"], "order": r["order"],
                "model": key, "model_name": p["name"], "session": "newyork", "liquidity": key, "entry_model": key,
                "management": "BE at +1R" if p["management"] == 1 else "close half at +1R, then BE",
                "hold_hours": p["hold"], "outcome": r["outcome"], "r": r["r"], "filled": r["fill_i"] >= 0,
                "exit_time": m5.index[r["exit_i"]] + BAR if r["exit_i"] >= 0 else pd.NaT,
            })
    df = pd.DataFrame(out)
    return df.sort_values("signal_time").reset_index(drop=True) if len(df) else df
