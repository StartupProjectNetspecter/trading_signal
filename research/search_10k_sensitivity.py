"""Neighbour and hypothetical timestamp diagnostics; no re-selection of winners."""
import json
import struct

import numpy as np
import pandas as pd

from goldbot.config import load_config
from goldbot.smc.sessions import news_mask
from research.search_10k import OUT, BUILD, PARAMS, DTYPE, fold_ids, pack, run_engine
from research.search_10k_verify import read_binary


def opening_source(f, settings):
    idx = f.index
    local = idx.tz_convert("America/New_York")
    minute, day = local.hour*60+local.minute, local.tz_localize(None).normalize()
    begin, length = settings["start"], settings["length"]
    rows = []
    for dval in np.unique(day):
        r = np.flatnonzero((day == dval) & (minute >= begin) & (minute < begin+length))
        if len(r) != length//5 or not idx[r].to_series().diff().iloc[1:].eq(pd.Timedelta(minutes=5)).all():
            continue
        hi, lo = f.high.iloc[r].max(), f.low.iloc[r].min()
        t = np.flatnonzero((day == dval) & (np.arange(len(f)) > r[-1]) & (minute < 750))
        for i in t:
            d = 1 if f.close.iat[i] > hi else -1 if f.close.iat[i] < lo else 0
            if d:
                entry = (hi if d == 1 else lo) if settings["entry"] == "edge" else (hi+lo)/2+d*(hi-lo)/4
                rows.append(dict(i=int(i), d=d, entry=entry, stop_ref=lo if d == 1 else hi,
                                 order="limit", expiry_bars=12, window=begin))
                break
    return pack(rows)


def perform(a, raw, meta, params, selection, f):
    from research.search_10k_report import aggregate
    extra = a[a.enough_trades & a.family.isin(["opening_range", "bollinger_reentry"])].sort_values("score", ascending=False).groupby("family").head(1)
    ids = sorted(set(selection.values()) | set(extra.id.astype(int)))
    chosen = a[a.id.isin(ids)]
    neighbours = []
    for original in chosen.to_dict("records"):
        base = {key: original[key] for key in PARAMS}
        for key, values in {
            "buffer": [max(0.05, base["buffer"]-0.1), base["buffer"]+0.1],
            "rr": [max(0.5, base["rr"]-0.25), base["rr"]+0.25],
            "start": [max(0, base["start"]-30), base["start"]+30],
            "end": [base["end"]-30, min(1435, base["end"]+30)],
            "adx_min": [max(0, base["adx_min"]-5), base["adx_min"]+5],
            "hold": [2, 4, 8],
            "cap": [1, 2, 3],
        }.items():
            for value in values:
                if value == base[key]:
                    continue
                row = dict(base)
                row[key] = value
                if row["start"] >= row["end"]:
                    continue
                if row["rr"] <= 1:
                    row["management"] = 0
                row.update(id=100000+len(neighbours), original_id=int(original["id"]), changed=key)
                neighbours.append(row)
    neighbour_params = pd.DataFrame(neighbours).drop_duplicates(PARAMS[1:])
    neighbour_params[PARAMS].to_csv(BUILD / "neighbours.csv", index=False)
    neighbour_params.to_csv(OUT / "neighbour_configurations.csv", index=False)
    run_engine(BUILD / "neighbours.csv", OUT / "neighbour_raw.csv")
    nr = aggregate(pd.read_csv(OUT / "neighbour_raw.csv"), meta).merge(
        neighbour_params[["id", "original_id", "changed"]], on="id")
    nr.to_csv(OUT / "neighbour_results.csv", index=False)
    summary = []
    for trial, g in nr.groupby("original_id"):
        summary.append(dict(id=int(trial), neighbours=len(g),
                            positive_train_validation_pct=100*((g.train_avg_R > 0) & (g.validation_avg_R > 0)).mean(),
                            positive_test_pct=100*(g.test_avg_R > 0).mean(),
                            validation_PF_min=float(g.validation_PF.min()), validation_PF_max=float(g.validation_PF.max()),
                            test_PF_min=float(g.test_PF.min()), test_PF_max=float(g.test_PF.max())))
    pd.DataFrame(summary).to_csv(OUT / "neighbour_summary.csv", index=False)
    # This tests hypothetical offsets; it is deliberately not called a timestamp correction.
    t, v, k, sources = read_binary()
    labels = json.loads((OUT / "sources.json").read_text())
    selected_params = chosen[PARAMS]
    selected_params.to_csv(BUILD / "timing_params.csv", index=False)
    cfg = load_config()
    cfg["news"]["events_file"] = str(OUT / "news_events.csv")
    month_map = {m: i for i, m in enumerate(meta["months"])}
    results = []
    for shift in [2, 3]:
        shifted = f.copy()
        shifted.index = f.index+pd.Timedelta(hours=shift)
        shifted["close_time"] = shifted.index+pd.Timedelta(minutes=5)
        local = pd.DatetimeIndex(shifted.close_time).tz_convert("America/New_York")
        shifted["day"] = local.tz_localize(None).normalize()
        keys = [arr.copy() for arr in k]
        keys[0] = (local.hour*60+local.minute).to_numpy("<i4")
        keys[1] = np.array(local.strftime("%Y%m%d"), dtype="<i4")
        keys[2] = local.weekday.to_numpy("<i4")
        keys[3] = (news_mask(shifted.index, cfg) | news_mask(pd.DatetimeIndex(shifted.close_time), cfg)).astype("<i4")
        keys[8] = fold_ids(shifted.day)
        keys[9] = np.array([month_map[s] for s in local.strftime("%Y-%m")], dtype="<i4")
        shifted_sources = list(sources)
        for src in chosen.source.unique():
            src = int(src)
            label = labels[src]
            if label["family"] == "opening_range":
                shifted_sources[src] = opening_source(shifted, label["settings"])
            elif label["family"] not in ["hhhl_pullback", "ema_pullback", "bollinger_reentry"]:
                raise ValueError("Timestamp diagnostics need a dedicated source rebuild for "+label["family"])
        path = BUILD / f"timing_{shift}.bin"
        with open(path, "wb") as dest:
            dest.write(struct.pack("<4i", 20261015, len(t), len(meta["months"]), 8))
            (t+shift*3600).astype("<i8").tofile(dest)
            for arr in v+keys:
                arr.tofile(dest)
            dest.write(struct.pack("<i", len(shifted_sources)))
            for arr in shifted_sources:
                dest.write(struct.pack("<i", len(arr)))
                arr.tofile(dest)
        output = OUT / f"timing_plus{shift}h_raw.csv"
        run_engine(BUILD / "timing_params.csv", output, data_path=path)
        shifted_meta = dict(meta)
        shifted_meta["fold_days"] = {str(i): int(shifted.loc[(keys[8] == i) & (keys[2] < 5), "day"].nunique()) for i in range(8)}
        score = aggregate(pd.read_csv(output), shifted_meta)
        score["hypothetical_offset_hours"] = shift
        results.append(score)
    base = aggregate(raw[raw.id.isin(ids)], meta)
    base["hypothetical_offset_hours"] = 0
    pd.concat([base]+results, ignore_index=True).to_csv(OUT / "timestamp_sensitivity.csv", index=False)
