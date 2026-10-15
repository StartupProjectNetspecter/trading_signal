"""Scalping research on gold M1.  python -m research.scalping_test

Three scalping setups with M1 entries and M15 trend direction, London+NY (02:00-12:00 NY):
  A. micro-ICT: M1 sweep of the last-60-bar high/low -> M1 CHoCH within 15 bars -> limit at M1 FVG/OB (50%)
  B. EMA pullback: EMA9>EMA21 (M1) with M15 trend up; bar dips to EMA21 and closes back above with a bullish body
  C. M5 BOS + M1 FVG: after an M5 break of structure in the M15 direction, first M1 FVG in that direction -> limit at 50%
Costs: spread $0.30 and $0.60 (stress). Honest split: choose on 2023-24, confirm 2025, report 2026.
"""
import itertools

import numpy as np
import pandas as pd

from goldbot.backtest.engine import simulate
from goldbot.config import load_config, resolve
from goldbot.data.store import resample
from goldbot.smc.indicators import atr
from goldbot.smc.structure import market_structure
from goldbot.smc.swings import last_confirmed, swing_points
from goldbot.smc.sessions import news_mask

M1 = pd.Timedelta(minutes=1)


def load_m1():
    df = pd.read_csv(resolve("data/mt5_XAUUSD_M1.csv"), index_col="time")
    df.index = pd.to_datetime(df.index).tz_localize("UTC")
    return df


def context(m1, cfg):
    def align(tf):
        htf = resample(m1, tf)
        right = pd.DataFrame({"t": htf.index + pd.Timedelta(tf), "v": market_structure(htf, 2)["trend"].to_numpy()})
        return pd.merge_asof(pd.DataFrame({"t": m1.index + M1}), right, on="t", direction="backward")["v"].fillna(0).to_numpy()

    m5 = resample(m1, "5min")
    ev5 = market_structure(m5, 2)["event"]
    right = pd.DataFrame({"t": m5.index + pd.Timedelta("5min"), "e": ev5.to_numpy()})
    m5_event = pd.merge_asof(pd.DataFrame({"t": m1.index + M1}), right, on="t", direction="backward", tolerance=pd.Timedelta("59s"))["e"].fillna("").to_numpy()
    ny = (m1.index + M1).tz_convert("America/New_York")
    return {
        "m15": align("15min"), "m5_event": m5_event,
        "minute": (ny.hour * 60 + ny.minute).to_numpy(), "wd": ny.weekday.to_numpy(),
        "day": ny.tz_localize(None).normalize().to_numpy(),
        "news": news_mask(m1.index, cfg),
        "atr": atr(m1, 14).to_numpy(),
    }


def _sig(m1, i, d, entry, sl, rr, order, expiry):
    risk = (entry - sl) * d
    return {"signal_time": m1.index[i] + M1, "expiry_time": m1.index[i] + M1 * (1 + expiry), "direction": "BUY" if d == 1 else "SELL",
            "entry": round(entry, 2), "sl": round(sl, 2), "tp": round(entry + d * rr * risk, 2), "rr": rr, "order": order}


def generate(m1, ctx, concept, rr, sl_buf=0.3, max_day=4, cooldown=15):
    o, h, l, c = (m1[k].to_numpy() for k in ("open", "high", "low", "close"))
    a, m15, minute, news, wd, day = ctx["atr"], ctx["m15"], ctx["minute"], ctx["news"], ctx["wd"], ctx["day"]
    ok = (minute >= 120) & (minute < 720) & (wd < 5) & ~news & np.isfinite(a)
    sigs, last, count, cur_day = [], -10**9, 0, None
    if concept == "micro_ict":
        sh, sl_ = swing_points(h, l, 2)
        shl, _ = last_confirmed(h, sh, 2)
        sll, _ = last_confirmed(l, sl_, 2)
        lo60 = pd.Series(l).shift(1).rolling(60).min().to_numpy()
        hi60 = pd.Series(h).shift(1).rolling(60).max().to_numpy()
        state = {1: None, -1: None}
        for i in range(61, len(m1)):
            for d in (1, -1):
                swept = l[i] < lo60[i] if d == 1 else h[i] > hi60[i]
                st = state[d]
                if swept and (st is None or (l[i] if d == 1 else h[i]) * d < st["ext"] * d):
                    lvl = shl[i] if d == 1 else sll[i]
                    state[d] = st = {"start": i if st is None else st["start"], "ext": l[i] if d == 1 else h[i], "ext_i": i,
                                     "choch": lvl if st is None else st["choch"]}
                if st is None:
                    continue
                if i - st["start"] > 15 or np.isnan(st["choch"]):
                    state[d] = None
                    continue
                if (c[i] - st["choch"]) * d <= 0:
                    continue
                state[d] = None
                if not ok[i] or m15[i] != d or i - last < cooldown:
                    continue
                if day[i] != cur_day:
                    cur_day, count = day[i], 0
                if count >= max_day:
                    continue
                e = st["ext_i"]
                zone = None
                for k in range(i, e + 1, -1):  # latest M1 FVG in the reaction leg
                    if d == 1 and l[k] > h[k - 2]:
                        zone = (h[k - 2], l[k]); break
                    if d == -1 and h[k] < l[k - 2]:
                        zone = (h[k], l[k - 2]); break
                entry = (zone[0] + zone[1]) / 2 if zone else c[i]
                order = "limit" if zone else "market"
                sl = st["ext"] - d * sl_buf * a[i]
                if (entry - sl) * d < 0.5:
                    continue
                sigs.append(_sig(m1, i, d, entry, sl, rr, order, 10))
                last, count = i, count + 1
    elif concept == "ema_pullback":
        e9 = m1["close"].ewm(span=9, adjust=False).mean().to_numpy()
        e21 = m1["close"].ewm(span=21, adjust=False).mean().to_numpy()
        low5 = pd.Series(l).rolling(5).min().to_numpy()
        high5 = pd.Series(h).rolling(5).max().to_numpy()
        for i in np.flatnonzero(ok):
            if i < 30 or i - last < cooldown:
                continue
            for d in (1, -1):
                trend = (e9[i] - e21[i]) * d > 0 and m15[i] == d
                touch = l[i] <= e21[i] if d == 1 else h[i] >= e21[i]
                reject = (c[i] - e21[i]) * d > 0 and (c[i] - o[i]) * d > 0.3 * a[i]
                if not (trend and touch and reject):
                    continue
                if day[i] != cur_day:
                    cur_day, count = day[i], 0
                if count >= max_day:
                    break
                sl = (low5[i] if d == 1 else high5[i]) - d * sl_buf * a[i]
                if (c[i] - sl) * d < 0.5:
                    break
                sigs.append(_sig(m1, i, d, c[i], sl, rr, "market", 1))
                last, count = i, count + 1
                break
    elif concept == "bos_fvg":
        ev = ctx["m5_event"]
        armed = {1: -1, -1: -1}
        for i in range(2, len(m1)):
            if ev[i].startswith("BOS"):
                armed[1 if ev[i].endswith("_UP") else -1] = i
            for d in (1, -1):
                if armed[d] < 0 or i - armed[d] > 30:
                    continue
                fvg = l[i] > h[i - 2] if d == 1 else h[i] < l[i - 2]
                if not fvg or not ok[i] or m15[i] != d or i - last < cooldown:
                    continue
                armed[d] = -1
                if day[i] != cur_day:
                    cur_day, count = day[i], 0
                if count >= max_day:
                    continue
                lo_, hi_ = (h[i - 2], l[i]) if d == 1 else (h[i], l[i - 2])
                entry = (lo_ + hi_) / 2
                sl = (min(l[i - 2], l[i - 1]) if d == 1 else max(h[i - 2], h[i - 1])) - d * sl_buf * a[i]
                if (entry - sl) * d < 0.5:
                    continue
                sigs.append(_sig(m1, i, d, entry, sl, rr, "limit", 10))
                last, count = i, count + 1
    return pd.DataFrame(sigs)


def evaluate(sig, m1, cfg, spread):
    c = {**cfg, "backtest": {**cfg["backtest"], "spread_usd": spread, "max_hold_bars": 60},
         "strategy": {**cfg["strategy"], "partial_at_r": None, "breakeven_at_r": None}}
    t = simulate(sig, m1, c)
    t = t[t["filled"]]
    per = np.where(t["signal_time"] < "2025-01-01", "train", np.where(t["signal_time"] < "2026-01-01", "valid", "test"))
    out = {}
    for p in ("train", "valid", "test", "all"):
        r = t["r"].to_numpy() if p == "all" else t["r"].to_numpy()[per == p]
        loss = -r[r < 0].sum()
        out[p] = dict(n=len(r), win=round(100 * (r > 0).mean(), 1) if len(r) else 0, PF=round(r[r > 0].sum() / loss, 2) if loss else 0, R=round(r.sum(), 1))
    return out


def main():
    cfg = load_config()
    m1 = load_m1()
    print(f"M1 bars: {len(m1):,}. Building context...", flush=True)
    ctx = context(m1, cfg)
    weeks = (m1.index[-1] - m1.index[0]).days / 7
    rows = []
    for concept, rr in itertools.product(["micro_ict", "ema_pullback", "bos_fvg"], [1.0, 1.5, 2.0]):
        sig = generate(m1, ctx, concept, rr)
        for spread in (0.30, 0.60):
            res = evaluate(sig, m1, cfg, spread) if len(sig) else None
            if not res:
                continue
            rows.append(dict(setup=concept, rr=rr, spread=spread, per_week=round(res["all"]["n"] / weeks, 1),
                             win=res["all"]["win"], PF=res["all"]["PF"], R=res["all"]["R"],
                             PF_2324=res["train"]["PF"], PF_2025=res["valid"]["PF"], PF_2026=res["test"]["PF"], win_2026=res["test"]["win"]))
        print(f"  done {concept} RR {rr}: {len(sig)} signals", flush=True)
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print(df.to_string(index=False))
    df.to_csv(resolve("research/scalping_results.csv"), index=False)


if __name__ == "__main__":
    main()
