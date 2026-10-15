"""Reproducible 10,000-model search, compiled local engine and complete provenance.

python -m research.search_10k prepare
python -m research.search_10k run
python -m research.search_10k finish
"""
import argparse
import hashlib
import itertools
import json
import struct
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from goldbot.config import ROOT, load_config
from goldbot.data.store import load_m5, resample
from goldbot.smc.indicators import atr
from goldbot.smc.structure import market_structure
from goldbot.strategy import mtf_confluence
from research.causal_gold import features, proposals, confirmed_structure, BAR

OUT = ROOT / "reports" / "search_10k"
BUILD = ROOT / "research" / ".search_build"
COMPILER = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
FAMILIES = ["hhhl_pullback", "bos", "ema_pullback", "sweep_reclaim", "rsi_reversal",
            "bollinger_reentry", "silver_bullet", "opening_range", "donchian", "mtf_confluence"]
PARAMS = ["id", "source", "bias", "start", "end", "cap", "cooldown", "stop_mode", "buffer",
          "rr", "min_risk", "max_risk", "expiry", "hold", "management", "direction",
          "adx_min", "adx_max", "body", "vol_min", "vol_max", "q1", "q2", "flags"]
DTYPE = np.dtype([("i", "<i4"), ("d", "<i4"), ("entry", "<f8"), ("stop_ref", "<f8"),
                  ("order", "<i4"), ("expiry_bars", "<i4"), ("window", "<i4"),
                  ("q1", "<f8"), ("q2", "<f8"), ("flags", "<i4")])


def hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fold_ids(day):
    d = pd.DatetimeIndex(day)
    return np.select([d.year == 2023, d.year == 2024, (d.year == 2025) & (d.quarter == 1),
                      (d.year == 2025) & (d.quarter == 2), (d.year == 2025) & (d.quarter == 3),
                      (d.year == 2025) & (d.quarter == 4), (d.year == 2026) & (d.month <= 6)],
                     list(range(7)), default=7).astype("<i4")


def enrich(m5, cfg):
    f = features(m5, cfg)
    for n in [4, 5]:
        s = confirmed_structure(m5, n)
        for col in s:
            f[f"s{n}_{col}"] = s[col]
        f[f"s{n}_event"] = market_structure(m5, n).event
    m15 = resample(m5, "15min")
    count = m5.close.resample("15min").count()
    m15 = m15[count.reindex(m15.index) == 3]
    right = pd.DataFrame({"t": m15.index+pd.Timedelta(minutes=15),
                          "m15_bos": market_structure(m15, 2).trend.to_numpy(),
                          "m15_hhhl": confirmed_structure(m15, 2).trend.to_numpy()})
    aligned = pd.merge_asof(pd.DataFrame({"t": f.close_time.to_numpy()}), right, on="t", direction="backward")
    f["m15_bos"] = aligned.m15_bos.fillna(0).to_numpy()
    f["m15_hhhl"] = aligned.m15_hhhl.fillna(0).to_numpy()
    up = m5.high.diff()
    down = -m5.low.diff()
    plus = up.where((up > down) & (up > 0), 0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    minus = down.where((down > up) & (down > 0), 0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    total = plus+minus
    dx = (100*(plus-minus).abs()/total.replace(0, np.nan)).fillna(0)
    f["adx"] = dx.ewm(alpha=1/14, adjust=False, min_periods=28).mean()
    f["body"] = (f.close-f.open).abs()/f.atr
    f["volratio"] = f.atr/f.atr.rolling(288, min_periods=288).mean()
    return f.copy()


def pack(rows):
    if not rows:
        return np.zeros(0, dtype=DTYPE)
    out = np.zeros(len(rows), dtype=DTYPE)
    for k, row in enumerate(rows):
        out[k] = (row["i"], row["d"], row["entry"], row["stop_ref"],
                  0 if row["order"] == "market" else 1, row.get("expiry_bars", 12),
                  row.get("window", -1), row.get("q1", 100), row.get("q2", 100), row.get("flags", 255))
    return np.sort(out, order=["i", "d"])


def from_masks(f, buy, sell, stop_buy, stop_sell):
    rows = []
    for d, mask, stop in [(1, buy, stop_buy), (-1, sell, stop_sell)]:
        pos = np.flatnonzero(mask.fillna(False).to_numpy())
        for i in pos:
            rows.append(dict(i=int(i), d=d, entry=f.close.iat[i], stop_ref=stop.iat[i], order="market", expiry_bars=1))
    return rows


def sources(m5, f, cfg):
    result, labels = [], []
    def add(family, label, rows):
        result.append(pack(rows))
        labels.append(dict(source=len(result)-1, family=family, settings=label, raw_setups=len(rows)))
    for family in ["hhhl_pullback", "bos"]:
        for n in [2, 3, 4, 5]:
            add(family, dict(swing_n=n), proposals(f, family, n))
    for fast, slow in [(9, 21), (13, 34), (21, 55), (34, 89), (50, 200)]:
        ef = f.close.ewm(span=fast, adjust=False, min_periods=fast).mean()
        es = f.close.ewm(span=slow, adjust=False, min_periods=slow).mean()
        buy = (ef > es) & (f.close.shift(1) <= ef.shift(1)) & (f.close > ef) & (f.close > f.open)
        sell = (ef < es) & (f.close.shift(1) >= ef.shift(1)) & (f.close < ef) & (f.close < f.open)
        add("ema_pullback", dict(fast=fast, slow=slow), from_masks(f, buy, sell, f.low6, f.high6))
    for length in [12, 24, 48, 96]:
        lo, hi = f.low.rolling(length).min().shift(1), f.high.rolling(length).max().shift(1)
        buy = (f.low < lo) & (f.close > lo) & (f.close > f.open)
        sell = (f.high > hi) & (f.close < hi) & (f.close < f.open)
        add("sweep_reclaim", dict(lookback=length), from_masks(f, buy, sell, f.low, f.high))
        buy = (f.close > hi) & (f.close.shift(1) <= hi.shift(1))
        sell = (f.close < lo) & (f.close.shift(1) >= lo.shift(1))
        add("donchian", dict(lookback=length), from_masks(f, buy, sell, f.low12, f.high12))
    for length, lower in itertools.product([7, 14, 21], [20, 25, 30, 35]):
        diff = f.close.diff()
        gain = diff.clip(lower=0).ewm(alpha=1/length, adjust=False, min_periods=length).mean()
        loss = (-diff.clip(upper=0)).ewm(alpha=1/length, adjust=False, min_periods=length).mean()
        rsi = pd.Series(np.where(loss > 0, 100-100/(1+gain/loss), np.where(gain > 0, 100, 50)), index=f.index)
        buy = (rsi.shift(1) < lower) & (rsi >= lower) & (f.close > f.open)
        sell = (rsi.shift(1) > 100-lower) & (rsi <= 100-lower) & (f.close < f.open)
        add("rsi_reversal", dict(period=length, lower=lower, upper=100-lower), from_masks(f, buy, sell, f.low6, f.high6))
    for length, width in itertools.product([20, 40], [1.5, 2.0, 2.5]):
        mid, sd = f.close.rolling(length).mean(), f.close.rolling(length).std(ddof=0)
        lo, hi = mid-width*sd, mid+width*sd
        buy = (f.close.shift(1) < lo.shift(1)) & (f.close > lo) & (f.close > f.open)
        sell = (f.close.shift(1) > hi.shift(1)) & (f.close < hi) & (f.close < f.open)
        add("bollinger_reentry", dict(period=length, stddev=width), from_masks(f, buy, sell, f.low6, f.high6))
    rows = []
    for begin, end in [(180, 240), (600, 660), (840, 900)]:
        for i in np.flatnonzero(((f.minute >= begin) & (f.minute < end) & f.consecutive3).to_numpy()):
            a = f.atr.iat[i]
            if not np.isfinite(a) or a <= 0:
                continue
            for d in [1, -1]:
                if (f.close.iat[i-1]-f.open.iat[i-1])*d <= 0:
                    continue
                bottom, top = ((f.high.iat[i-2], f.low.iat[i]) if d == 1 else (f.high.iat[i], f.low.iat[i-2]))
                if (top-bottom)/a < 0.05:
                    continue
                rows.append(dict(i=int(i), d=d, entry=(bottom+top)/2,
                                 stop_ref=f.low.iloc[i-2:i+1].min() if d == 1 else f.high.iloc[i-2:i+1].max(),
                                 order="limit", expiry_bars=(end-int(f.minute.iat[i]))//5+6, window=begin,
                                 q1=(top-bottom)/a, q2=abs(f.close.iat[i-1]-f.open.iat[i-1])/a))
    add("silver_bullet", dict(windows=[[180, 240], [600, 660], [840, 900]]), rows)
    local = m5.index.tz_convert("America/New_York")
    minute, day = local.hour*60+local.minute, local.tz_localize(None).normalize()
    for begin, length, entry_mode in itertools.product([500, 510, 570], [15, 30], ["edge", "mid_retest"]):
        rows = []
        for dval in np.unique(day):
            r = np.flatnonzero((day == dval) & (minute >= begin) & (minute < begin+length))
            if len(r) != length//5 or not m5.index[r].to_series().diff().iloc[1:].eq(BAR).all():
                continue
            hi, lo = f.high.iloc[r].max(), f.low.iloc[r].min()
            t = np.flatnonzero((day == dval) & (np.arange(len(f)) > r[-1]) & (minute < 750))
            for i in t:
                d = 1 if f.close.iat[i] > hi else -1 if f.close.iat[i] < lo else 0
                if d:
                    entry = (hi if d == 1 else lo) if entry_mode == "edge" else (hi+lo)/2+d*(hi-lo)/4
                    rows.append(dict(i=int(i), d=d, entry=entry, stop_ref=lo if d == 1 else hi,
                                     order="limit", expiry_bars=12, window=begin, q1=100, q2=100))
                    break
        add("opening_range", dict(start=begin, length=length, entry=entry_mode), rows)
    mc_cfg = {**cfg, "strategy": {**cfg["strategy"], "mtf": dict(m5_swing_n=2, m15_swing_n=2,
               zone_max_age_bars=144, zone_break_atr=0.5, max_bars_tap_to_choch=24,
               sl_buffer_atr=0.3, displacement_atr=0.7)}}
    print("Computing H1/M15/M5 zone candidates...", flush=True)
    cands = mtf_confluence.candidates(m5, mc_cfg)
    for mode in ["market", "limit"]:
        rows = []
        for row in cands.to_dict("records"):
            entry = row[mode]
            if not np.isfinite(entry):
                continue
            flags = sum((1 << k) if row[name] else 0 for k, name in enumerate(
                ["h1_discount", "m15_ob", "m15_fvg", "sweep", "kill_zone", "displacement"]))
            rows.append(dict(i=int(m5.index.searchsorted(row["signal_time"]-BAR)), d=row["d"], entry=entry,
                             stop_ref=row["sl"]+row["d"]*0.3*row["atr"], order=mode, expiry_bars=12, flags=flags))
        add("mtf_confluence", dict(entry=mode, m5_swing_n=2, m15_swing_n=2, max_age_bars=144), rows)
    return result, labels


def make_trials(labels, count=10000):
    rng = np.random.default_rng(20261015)
    by_family = {family: [r["source"] for r in labels if r["family"] == family] for family in FAMILIES}
    rows, seen = [], set()
    for family in FAMILIES:
        for j in range(count//len(FAMILIES)):
            while True:
                source = int(rng.choice(by_family[family]))
                start, end = [(120, 300), (420, 600), (420, 720), (480, 900), (120, 900)][int(rng.integers(5))]
                rr = float(rng.choice([0.75, 1, 1.25, 1.5, 2, 2.5, 3]))
                management = int(rng.choice([0, 1, 2])) if rr > 1 else 0
                is_limit = family in ["silver_bullet", "opening_range"] or (family == "mtf_confluence" and labels[source]["settings"]["entry"] == "limit")
                q1, q2 = (float(rng.choice([0.05, 0.1, 0.2, 0.3])), float(rng.choice([0.3, 0.5, 0.75, 1]))) if family == "silver_bullet" else (0.0, 0.0)
                flags = int(rng.choice([0, 1, 8, 16, 32, 1|8, 1|32, 8|32])) if family == "mtf_confluence" else 0
                row = dict(id=len(rows), source=source, bias=int(rng.integers(5)), start=start, end=end,
                           cap=int(rng.choice([1, 2, 3])), cooldown=int(rng.choice([6, 12, 24])),
                           stop_mode=int(rng.choice([0, 0, 2, 3, 4, 6])), buffer=float(rng.choice([0.1, 0.2, 0.3, 0.5, 0.75])),
                           rr=rr, min_risk=float(rng.choice([1, 2, 3])), max_risk=float(rng.choice([4, 6, 8])),
                           expiry=int(rng.choice([6, 12, 24])) if is_limit else 1, hold=int(rng.choice([2, 4, 8])),
                           management=management, direction=int(rng.choice([0, 0, 1, -1])),
                           adx_min=float(rng.choice([0, 15, 20, 25])), adx_max=float(rng.choice([35, 50, 100])),
                           body=float(rng.choice([0, 0.2, 0.5])), vol_min=float(rng.choice([0, 0.5, 0.75])),
                           vol_max=float(rng.choice([1.5, 2, 100])), q1=q1, q2=q2, flags=flags)
                key = tuple(row[k] for k in PARAMS if k != "id")
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
                    break
    frame = pd.DataFrame(rows)
    frame["family"] = [labels[int(s)]["family"] for s in frame.source]
    return frame


def compile_engine():
    BUILD.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(COMPILER), "/nologo", "/optimize+", "/out:"+str(BUILD / "GoldSearch.exe"),
                    str(ROOT / "research" / "GoldSearch.cs")], check=True, cwd=ROOT)


def corrected_config():
    cfg = load_config()
    path = ROOT / cfg["news"]["events_file"]
    ev = pd.read_csv(path)
    ev = pd.concat([ev, pd.DataFrame([dict(datetime_utc="2023-01-12 13:30", event="CPI")])])
    ev["datetime_utc"] = pd.to_datetime(ev.datetime_utc, utc=True)
    ev.drop_duplicates().sort_values("datetime_utc").to_csv(OUT / "news_events.csv", index=False, date_format="%Y-%m-%d %H:%M")
    cfg["news"]["events_file"] = str(OUT / "news_events.csv")
    return cfg


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    cfg = corrected_config()
    m5 = load_m5(cfg)
    if m5.index.duplicated().any() or not m5.index.is_monotonic_increasing or m5.isna().any().any():
        raise ValueError("Invalid historical data")
    bad = (m5.high < m5[["open", "close", "low"]].max(axis=1)) | (m5.low > m5[["open", "close", "high"]].min(axis=1))
    if bad.any():
        raise ValueError("Invalid OHLC bounds")
    print("Building causal indicators...", flush=True)
    f = enrich(m5, cfg)
    raw, labels = sources(m5, f, cfg)
    trials = make_trials(labels)
    trials.to_csv(OUT / "configurations.csv", index=False)
    trials[PARAMS].to_csv(BUILD / "parameters.csv", index=False)
    f.to_pickle(BUILD / "features.pkl")
    (OUT / "sources.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")
    fold = fold_ids(f.day)
    month_labels = sorted(f.close_time.dt.tz_convert("America/New_York").dt.strftime("%Y-%m").unique())
    month_map = {m: i for i, m in enumerate(month_labels)}
    months = f.close_time.dt.tz_convert("America/New_York").dt.strftime("%Y-%m").map(month_map).to_numpy("<i4")
    arrays = [f[k].to_numpy("<f8") for k in ["open", "high", "low", "close", "atr", "rsi", "adx", "body", "volratio"]]
    keys = [f.minute.to_numpy("<i4"), f.day.dt.strftime("%Y%m%d").to_numpy("<i4"),
            f.weekday.to_numpy("<i4"), f.news.to_numpy("<i4")]
    keys += [f[k].to_numpy("<i4") for k in ["h1_bos", "h1_hhhl", "m15_bos", "m15_hhhl"]]
    keys += [fold, months]
    times = m5.index.as_unit("s").asi8.astype("<i8")
    with open(BUILD / "data.bin", "wb") as dest:
        dest.write(struct.pack("<4i", 20261015, len(m5), len(month_labels), 8))
        times.tofile(dest)
        for a in arrays+keys:
            a.tofile(dest)
        dest.write(struct.pack("<i", len(raw)))
        for a in raw:
            dest.write(struct.pack("<i", len(a)))
            a.tofile(dest)
    day_counts = {str(k): int(f.loc[fold == k, "day"][f.weekday < 5].nunique()) for k in range(8)}
    metadata = dict(seed=20261015, trials=len(trials), families=FAMILIES, bars=len(m5),
                    start=str(m5.index[0]), end=str(m5.index[-1]), months=month_labels, fold_days=day_counts,
                    folds=["2023", "2024", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026H1", "2026H2_partial"],
                    data_sha256=hash_file(ROOT / "data" / "mt5_XAUUSD_M5.csv"),
                    config_sha256=hash_file(ROOT / "config.yaml"), engine_sha256=hash_file(ROOT / "research" / "GoldSearch.cs"),
                    search_sha256=hash_file(Path(__file__)), features_sha256=hash_file(ROOT / "research" / "causal_gold.py"),
                    broker=broker_details(),
                    primary_costs=dict(spread=0.6, slippage=0.1, round_trip_commission_usd_per_oz=0,
                                       assumption="Official Exness Standard Cent terms: no trading commission. User fee discrepancy stress-tested separately."),
                    timestamp_status="CSV UTC labels not independently verified; downloader shifts MT5 timestamps despite official UTC documentation",
                    no_deployment=True)
    (OUT / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    compile_engine()
    print("Prepared", len(trials), "unique configurations from", len(labels), "causal setup sources", flush=True)


def broker_details():
    return dict(account="Exness MT5 Standard Cent", reported_min_spread=0.3,
                reported_commission_per_cent_lot_USC_roundtrip=0.5, leverage="1:2000",
                expected_symbol="XAUUSDc", cached_symbol="XAUUSD", contract_oz_per_cent_lot=None,
                official_commission="No trading commission", fee_discrepancy_unresolved=True,
                account_source="https://get.exness.help/hc/en-us/articles/17537782786588-Standard-Cent-account",
                metals_source="https://get.exness.help/hc/en-us/articles/17854173039388-Commodities")


def run_engine(param_path=None, output=None, spread=0.6, slippage=0.1, fee=0.0, detail=None, data_path=None):
    args = [str(BUILD / "GoldSearch.exe"), str(data_path or BUILD / "data.bin"), str(param_path or BUILD / "parameters.csv"),
            str(output or OUT / "raw_results.csv"), str(spread), str(slippage), str(fee)]
    if detail is not None:
        args.append(str(detail))
    subprocess.run(args, check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run", "finish"])
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    elif args.action == "run":
        meta = json.loads((OUT / "metadata.json").read_text())
        meta["broker"] = broker_details()
        meta["primary_costs"] = dict(spread=0.6, slippage=0.1, round_trip_commission_usd_per_oz=0,
                                      assumption="Official commission-free Standard Cent terms; reported fee checked as sensitivity scenarios")
        meta["search_sha256"] = hash_file(Path(__file__))
        (OUT / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        run_engine()
    else:
        from research.search_10k_report import finish
        finish()


if __name__ == "__main__":
    main()
