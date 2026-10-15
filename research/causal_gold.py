"""Isolated, causal research concepts. Never used by the live bot implicitly."""
import numpy as np
import pandas as pd

from goldbot.data.store import resample
from goldbot.smc.indicators import atr
from goldbot.smc.sessions import news_mask
from goldbot.smc.structure import market_structure
from goldbot.smc.swings import swing_points

BAR = pd.Timedelta(minutes=5)
CONCEPTS = ["hhhl_pullback", "bos", "ema_pullback", "sweep_reclaim",
            "rsi_reversal", "bollinger_reentry", "silver_bullet", "opening_range"]


def confirmed_structure(df, n=2, tolerance=0.01):
    """Compare consecutive same-side CONFIRMED pivots, available at j+n close.

    Equal levels are EH/EL, never HH/HL. Trend requires both HH+HL or LH+LL.
    Confirmation flags identify when a new pivot becomes knowable.
    """
    high, low = df.high.to_numpy(), df.low.to_numpy()
    ph, pl = swing_points(high, low, n)
    out = pd.DataFrame(index=df.index)
    for side, values, pivots, up, down, equal in [
        ("high", high, ph, "HH", "LH", "EH"),
        ("low", low, pl, "HL", "LL", "EL"),
    ]:
        last = previous = np.nan
        label, pivot_index = "", -1
        rows = []
        for i in range(len(df)):
            j = i - n
            confirmed = j >= 0 and pivots[j]
            if confirmed:
                previous, last, pivot_index = last, values[j], j
                label = ("first" if np.isnan(previous) else
                         up if last > previous + tolerance else
                         down if last < previous - tolerance else equal)
            rows.append((last, previous, label, pivot_index, confirmed))
        for k, col in enumerate([side, f"previous_{side}", f"{side}_label",
                                 f"{side}_pivot_index", f"{side}_confirmed"]):
            out[col] = [row[k] for row in rows]
    out["trend"] = np.select(
        [(out.high_label == "HH") & (out.low_label == "HL"),
         (out.high_label == "LH") & (out.low_label == "LL")], [1, -1], default=0)
    return out


def features(m5, cfg):
    f = m5.copy()
    f["atr"] = atr(m5, 14)
    f["close_time"] = m5.index + BAR
    local = pd.DatetimeIndex(f.close_time).tz_convert("America/New_York")
    f["day"] = local.tz_localize(None).normalize()
    f["minute"] = local.hour * 60 + local.minute
    f["weekday"] = local.weekday
    # Block decisions at CLOSE, plus blackout bars that overlap the interval.
    f["news"] = news_mask(m5.index, cfg) | news_mask(pd.DatetimeIndex(f.close_time), cfg)
    f["consecutive3"] = ((m5.index.to_series().diff() == BAR)
                         & (m5.index.to_series().diff().shift(1) == BAR)).to_numpy()
    for n in [2, 3]:
        structure = confirmed_structure(m5, n)
        for col in structure:
            f[f"s{n}_{col}"] = structure[col]
        f[f"s{n}_event"] = market_structure(m5, n).event
    h1 = resample(m5, "1h")
    counts = m5.close.resample("1h").count()
    h1 = h1[counts.reindex(h1.index) == 12]  # only complete H1 bars
    hstruct = confirmed_structure(h1, 2)
    right = pd.DataFrame({"known": h1.index + pd.Timedelta(hours=1),
                          "h1_bos": market_structure(h1, 2).trend.to_numpy(),
                          "h1_hhhl": hstruct.trend.to_numpy()})
    aligned = pd.merge_asof(pd.DataFrame({"known": f.close_time.to_numpy()}), right,
                           on="known", direction="backward")
    f["h1_bos"] = aligned.h1_bos.fillna(0).to_numpy()
    f["h1_hhhl"] = aligned.h1_hhhl.fillna(0).to_numpy()
    f["ema21"] = f.close.ewm(span=21, adjust=False, min_periods=21).mean()
    f["ema55"] = f.close.ewm(span=55, adjust=False, min_periods=55).mean()
    diff = f.close.diff()
    gain = diff.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-diff.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    f["rsi"] = np.where(loss > 0, 100 - 100 / (1 + gain / loss),
                        np.where(gain > 0, 100, 50))
    for length in [6, 12, 24]:
        f[f"low{length}"] = f.low.rolling(length).min()
        f[f"high{length}"] = f.high.rolling(length).max()
    mid = f.close.rolling(20).mean()
    sd = f.close.rolling(20).std(ddof=0)
    f["bb_low"], f["bb_high"] = mid - 2*sd, mid + 2*sd
    return f


def proposals(f, concept, n=2):
    """Return raw setups before directional/session/risk filters, each using closed bars."""
    up = f.close > f.open
    down = f.close < f.open
    prev = f.shift(1)
    if concept == "hhhl_pullback":
        buy = (f[f"s{n}_trend"] == 1) & f[f"s{n}_low_confirmed"] & up
        sell = (f[f"s{n}_trend"] == -1) & f[f"s{n}_high_confirmed"] & down
        stop_buy, stop_sell = f[f"s{n}_low"], f[f"s{n}_high"]
    elif concept == "bos":
        buy = f[f"s{n}_event"].str.endswith("_UP")
        sell = f[f"s{n}_event"].str.endswith("_DOWN")
        stop_buy, stop_sell = f[f"s{n}_low"], f[f"s{n}_high"]
    elif concept == "ema_pullback":
        buy = (f.ema21 > f.ema55) & (prev.close <= prev.ema21) & (f.close > f.ema21) & up
        sell = (f.ema21 < f.ema55) & (prev.close >= prev.ema21) & (f.close < f.ema21) & down
        stop_buy, stop_sell = f.low6, f.high6
    elif concept == "sweep_reclaim":
        buy = (f.low < prev.low12) & (f.close > prev.low12) & up
        sell = (f.high > prev.high12) & (f.close < prev.high12) & down
        stop_buy, stop_sell = f.low, f.high
    elif concept == "rsi_reversal":
        buy = (prev.rsi < 30) & (f.rsi >= 30) & up
        sell = (prev.rsi > 70) & (f.rsi <= 70) & down
        stop_buy, stop_sell = f.low6, f.high6
    elif concept == "bollinger_reentry":
        buy = (prev.close < prev.bb_low) & (f.close > f.bb_low) & up
        sell = (prev.close > prev.bb_high) & (f.close < f.bb_high) & down
        stop_buy, stop_sell = f.low6, f.high6
    else:
        return _timed_proposals(f, concept)
    rows = []
    for d, mask, stop in [(1, buy, stop_buy), (-1, sell, stop_sell)]:
        for i in np.flatnonzero(mask.fillna(False).to_numpy()):
            rows.append({"i": i, "d": d, "entry": f.close.iat[i],
                         "stop_ref": stop.iat[i], "order": "market", "expiry_bars": 1})
    return sorted(rows, key=lambda row: (row["i"], -row["d"]))


def _timed_proposals(f, concept):
    rows = []
    if concept == "silver_bullet":
        for begin, end in [(180, 240), (600, 660), (840, 900)]:
            inside = (f.minute >= begin) & (f.minute < end) & f.consecutive3
            for i in np.flatnonzero(inside.to_numpy()):
                a = f.atr.iat[i]
                if not np.isfinite(a) or abs(f.close.iat[i-1] - f.open.iat[i-1]) < 0.5*a:
                    continue
                for d in [1, -1]:
                    if (f.close.iat[i-1] - f.open.iat[i-1])*d <= 0:
                        continue
                    bottom, top = ((f.high.iat[i-2], f.low.iat[i]) if d == 1 else
                                   (f.high.iat[i], f.low.iat[i-2]))
                    if top-bottom < 0.1*a:
                        continue
                    entry = (bottom+top)/2
                    if (f.close.iat[i]-entry)*d <= 0:
                        continue
                    stop = f.low.iloc[i-2:i+1].min() if d == 1 else f.high.iloc[i-2:i+1].max()
                    # Scheduled expiry is causal even when the dataset is truncated mid-window.
                    rows.append({"i": i, "d": d, "entry": entry, "stop_ref": stop,
                                 "order": "limit", "expiry_bars": (end-int(f.minute.iat[i]))//5+6,
                                 "window": begin})
    elif concept == "opening_range":
        # 08:30-08:45 NY opening range; 3 complete M5 bars are mandatory.
        open_minute = (f.index.tz_convert("America/New_York").hour*60
                       + f.index.tz_convert("America/New_York").minute)
        day = f.index.tz_convert("America/New_York").tz_localize(None).normalize()
        for dval in np.unique(day):
            r = np.flatnonzero((day == dval) & (open_minute >= 510) & (open_minute < 525))
            if len(r) != 3 or not f.index[r].to_series().diff().iloc[1:].eq(BAR).all():
                continue
            hi, lo = f.high.iloc[r].max(), f.low.iloc[r].min()
            if not np.isfinite(f.atr.iat[r[-1]]) or hi-lo > 6*f.atr.iat[r[-1]]:
                continue
            t = np.flatnonzero((day == dval) & (np.arange(len(f)) > r[-1])
                               & (f.minute >= 530) & (f.minute < 690))
            for i in t:
                d = 1 if f.close.iat[i] > hi else -1 if f.close.iat[i] < lo else 0
                if d:
                    # Mid-retest: midpoint between range centre and broken edge.
                    entry = (hi+lo)/2 + d*(hi-lo)/4
                    rows.append({"i": i, "d": d, "entry": entry,
                                 "stop_ref": lo if d == 1 else hi,
                                 "order": "limit", "expiry_bars": 12, "window": 510})
                    break
    return sorted(rows, key=lambda row: (row["i"], -row["d"]))


def generate(f, raw, params, diagnostics=None):
    sigs, counts, last, windows = [], {}, -100, set()
    # Scalar access through numpy avoids repeated pandas indexing in large grids.
    cols = ["day", "weekday", "news", "minute", "atr", "close_time", "h1_bos", "h1_hhhl",
            "rsi", "ema21", "ema55"] + [f"s{params.get('n', 2)}_{name}" for name in
                                          ["high_label", "low_label", "high", "low"]]
    values = {col: f[col].to_numpy() for col in cols}
    diag = {"raw_setups": len(raw)}
    def reject(reason):
        diag[reason] = diag.get(reason, 0)+1
    start, end = (420, 900) if params["session"] == "ny" else (120, 900)
    for row in raw:
        i, d = row["i"], row["d"]
        day = values["day"][i]
        if values["weekday"][i] >= 5:
            reject("weekend")
            continue
        if values["news"][i]:
            reject("news")
            continue
        if not start <= values["minute"][i] < end:
            reject("outside_session")
            continue
        if i-last < 12:
            reject("cooldown")
            continue
        if counts.get(day, 0) >= 2:
            reject("daily_cap")
            continue
        if params["bias"] != "none" and values[params["bias"]][i] != d:
            reject("htf_disagrees_or_neutral")
            continue
        key = (day, row.get("window"))
        if "window" in row and key in windows:
            reject("window_already_used")
            continue
        a = values["atr"][i]
        entry = round(row["entry"], 2)
        sl = round(row["stop_ref"]-d*params["buffer"]*a, 2)
        risk = (entry-sl)*d
        if not np.isfinite(risk) or risk < 1.0 or risk > params.get("max_risk_atr", 8)*a:
            reject("invalid_or_outside_risk_bounds")
            continue
        tp = round(entry+d*params["rr"]*risk, 2)
        sigs.append({"signal_time": values["close_time"][i],
                     "expiry_time": values["close_time"][i]+row["expiry_bars"]*BAR,
                     "direction": "BUY" if d == 1 else "SELL", "entry": entry,
                     "sl": sl, "tp": tp, "order": row["order"],
                     "concept": params["concept"], "atr": a,
                     "high_label": values[f"s{params.get('n', 2)}_high_label"][i],
                     "low_label": values[f"s{params.get('n', 2)}_low_label"][i],
                     "last_high": values[f"s{params.get('n', 2)}_high"][i],
                     "last_low": values[f"s{params.get('n', 2)}_low"][i],
                     "h1_bos": values["h1_bos"][i], "h1_hhhl": values["h1_hhhl"][i],
                     "rsi": values["rsi"][i], "ema21": values["ema21"][i],
                     "ema55": values["ema55"][i], "risk_atr": risk/a})
        counts[day], last = counts.get(day, 0)+1, i
        windows.add(key)
    diag["signals"] = len(sigs)
    if diagnostics is not None:
        diagnostics.update(diag)
    return pd.DataFrame(sigs)


def execute(signals, m5, spread=0.3, slippage=0.05, commission=0.0):
    """Research execution: one pending order/position; costs in USD per ounce.

    No partials or BE. Limit fills at stated price, stop-first intrabar ambiguity,
    no fill-bar TP, gap-aware stops, elapsed-time expiry/8h hold, next-open markets.
    Fixed per-ounce round-trip commission is an explicit scenario assumption.
    """
    idx = m5.index
    o, h, l, c = (m5[k].to_numpy() for k in ["open", "high", "low", "close"])
    rows, free = [], idx[0]
    for s in signals.sort_values("signal_time").to_dict("records") if len(signals) else []:
        rec = dict(s, filled=False, fill_time=pd.NaT, exit_time=pd.NaT, r=np.nan)
        if s["signal_time"] < free:
            rows.append(dict(rec, outcome="capacity"))
            continue
        d = 1 if s["direction"] == "BUY" else -1
        entry, sl, tp = s["entry"], s["sl"], s["tp"]
        start = idx.searchsorted(s["signal_time"])
        fill = None
        reason = "expired"
        for j in range(start, min(idx.searchsorted(s["expiry_time"]), len(idx))):
            ask_open = o[j]+spread
            # Do not open beyond either bracket. Gap has already invalidated the setup.
            close_open = o[j] if d == 1 else ask_open
            if (close_open-sl)*d <= 0 or (close_open-tp)*d >= 0:
                reason, free = "invalid_gap", idx[j]+BAR
                break
            if s["order"] == "market":
                px = ask_open+slippage if d == 1 else o[j]-slippage
                fill = j
            elif (l[j]+spread <= entry if d == 1 else h[j] >= entry):
                fill, px = j, entry
            if fill is not None:
                if (px-sl)*d <= 0 or (tp-px)*d <= 0:
                    fill, reason, free = None, "invalid_fill", idx[j]+BAR
                break
            if (h[j] >= tp if d == 1 else l[j]+spread <= tp):
                reason, free = "cancelled", idx[j]+BAR
                break
        if fill is None:
            if reason == "expired":
                free = s["expiry_time"]
            rows.append(dict(rec, outcome=reason))
            continue
        risk = (px-sl)*d
        deadline = idx[fill]+pd.Timedelta(hours=8)
        last = min(idx.searchsorted(deadline, side="left")-1, len(idx)-1)
        exit_j, exit_px, outcome = last, c[last]+(spread if d == -1 else 0)-d*slippage, "time"
        for j in range(fill, last+1):
            lo, hi, op = ((l[j], h[j], o[j]) if d == 1 else
                          (l[j]+spread, h[j]+spread, o[j]+spread))
            if (lo <= sl if d == 1 else hi >= sl):
                exit_px = (min(sl, op) if d == 1 else max(sl, op))-d*slippage
                exit_j, outcome = j, "sl"
                break
            if j > fill and (hi >= tp if d == 1 else lo <= tp):
                exit_j, exit_px, outcome = j, tp, "tp"
                break
        free = idx[exit_j]+BAR
        rows.append(dict(rec, filled=True, fill_time=idx[fill], exit_time=free,
                         fill_price=px, exit_price=exit_px, actual_risk=risk,
                         outcome=outcome, r=((exit_px-px)*d-commission)/risk))
    return pd.DataFrame(rows)
