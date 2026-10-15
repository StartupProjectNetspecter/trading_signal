"""Independent Python calculation checks for the compiled 10k search engine."""
import json
import math
import struct

import numpy as np
import pandas as pd

from research.search_10k import OUT, BUILD, PARAMS, DTYPE, run_engine


def read_binary(path=None):
    with open(path or BUILD / "data.bin", "rb") as src:
        magic, n, months, folds = struct.unpack("<4i", src.read(16))
        assert magic == 20261015
        t = np.fromfile(src, "<i8", n)
        v = [np.fromfile(src, "<f8", n) for _ in range(9)]
        k = [np.fromfile(src, "<i4", n) for _ in range(10)]
        count, = struct.unpack("<i", src.read(4))
        sources = []
        for _ in range(count):
            length, = struct.unpack("<i", src.read(4))
            sources.append(np.fromfile(src, DTYPE, length))
        assert src.tell() == src.seek(0, 2)
    return t, v, k, sources


def round_cent(x):
    # .NET rounds to nearest even at two decimal places.
    return float(np.rint(x*100)/100)


def reference(data, p, spread=0.6, slip=0.1, fee=0):
    t, v, k, sources = data
    o, h, l, c, a, rsi, adx, body, vol = v
    minute, day, wd, news, h1, hhhl, m15, m15hhhl, fold, month = k
    last, last_day, count, free = -100000, -1, 0, -10**18
    windows, records = set(), []
    for row in sources[int(p["source"])]:
        i, d = int(row["i"]), int(row["d"])
        if wd[i] >= 5 or news[i] or not p["start"] <= minute[i] < p["end"] or i-last < p["cooldown"]:
            continue
        if p["direction"] and p["direction"] != d:
            continue
        if p["bias"] and k[int(p["bias"])+3][i] != d:
            continue
        if (not np.isfinite(adx[i]) or not np.isfinite(vol[i]) or not p["adx_min"] <= adx[i] <= p["adx_max"]
                or body[i] < p["body"] or not p["vol_min"] <= vol[i] <= p["vol_max"]):
            continue
        if row["q1"] < p["q1"] or row["q2"] < p["q2"] or int(row["flags"]) & int(p["flags"]) != p["flags"]:
            continue
        if day[i] != last_day:
            last_day, count = day[i], 0
        if count >= p["cap"]:
            continue
        window = (int(day[i]), int(row["window"]))
        if row["window"] >= 0 and window in windows:
            continue
        entry = round_cent(row["entry"])
        ref = row["stop_ref"] if p["stop_mode"] == 0 else entry-d*p["stop_mode"]*a[i]/2
        stop = round_cent(ref-d*p["buffer"]*a[i])
        planned = (entry-stop)*d
        if not np.isfinite(planned) or not np.isfinite(a[i]) or planned < p["min_risk"] or planned > p["max_risk"]*a[i]:
            continue
        target = round_cent(entry+d*p["rr"]*planned)
        if (target-entry)*d <= 0:
            continue
        last, count = i, count+1
        if row["window"] >= 0:
            windows.add(window)
        rec = dict(id=int(p["id"]), signal_i=i, d=d, entry=entry, sl=stop, tp=target,
                   fill_i=-1, fill_price=0.0, exit_i=-1, exit_price=0.0, r=0.0, outcome="expired", fold=int(fold[i]))
        signal = t[i]+300
        if signal < free:
            records.append(dict(rec, outcome="capacity"))
            continue
        start = t.searchsorted(signal)
        expiry_bars = 1 if row["order"] == 0 else p["expiry"] or row["expiry_bars"]
        expiry = signal+300*expiry_bars
        fill, px, reason = -1, 0.0, "expired"
        for j in range(start, len(t)):
            if t[j] >= expiry:
                break
            if news[j]:
                reason, free = "news_cancel", t[j]+300
                break
            op = o[j]+(spread if d == -1 else 0)
            if (op-stop)*d <= 0 or (op-target)*d >= 0:
                reason, free = "invalid_gap", t[j]+300
                break
            if row["order"] == 0:
                fill, px = j, o[j]+(spread+slip if d == 1 else -slip)
            elif l[j]+spread <= entry if d == 1 else h[j] >= entry:
                fill, px = j, entry
            if fill >= 0:
                risk = (px-stop)*d
                if risk <= 0 or (target-px)*d <= 0:
                    fill, reason, free = -1, "invalid_fill", t[j]+300
                break
            if h[j] >= target if d == 1 else l[j]+spread <= target:
                reason, free = "cancelled", t[j]+300
                break
        if fill < 0:
            if reason == "expired":
                free = expiry
            records.append(dict(rec, outcome=reason))
            continue
        risk = (px-stop)*d
        deadline = t[fill]+int(p["hold"])*3600
        maximum = min(t.searchsorted(deadline)-1, len(t)-1)
        active_stop, size, banked, partial = stop, 1.0, 0.0, False
        exit_i, exit_px, outcome = -1, 0.0, "time"
        for j in range(fill, maximum+1):
            lo, hi, op = l[j]+(spread if d == -1 else 0), h[j]+(spread if d == -1 else 0), o[j]+(spread if d == -1 else 0)
            if lo <= active_stop if d == 1 else hi >= active_stop:
                exit_i = j
                exit_px = (min(active_stop, op) if d == 1 else max(active_stop, op))-d*slip
                outcome = "sl" if active_stop == stop else "be"
                break
            if j == fill:
                continue
            best, one = (hi if d == 1 else lo), px+d*risk
            if p["management"] == 2 and not partial and (target-one)*d > 0 and (best-one)*d >= 0:
                size, banked, partial = 0.5, 0.5*risk, True
            if (best-target)*d >= 0:
                exit_i, exit_px, outcome = j, target, "tp"
                break
            if p["management"] > 0 and (target-one)*d > 0 and (best-one)*d >= 0:
                active_stop = px
        if exit_i < 0:
            nxt = maximum+1
            if nxt < len(t) and t[nxt] > deadline and t[maximum]+300 < deadline:
                exit_i, exit_px, outcome = nxt, o[nxt]+(spread if d == -1 else 0)-d*slip, "time_gap"
            else:
                exit_i, exit_px = maximum, c[maximum]+(spread if d == -1 else 0)-d*slip
                if maximum == len(t)-1 and t[maximum]+300 < deadline:
                    outcome = "end_censored"
        free = t[exit_i]+300
        r = (banked+size*(exit_px-px)*d-fee)/risk
        records.append(dict(rec, fill_i=fill, fill_price=px, exit_i=exit_i, exit_price=exit_px,
                            r=r, outcome=outcome+("+partial" if partial else "")))
    return pd.DataFrame(records)


def verify():
    configurations = pd.read_csv(OUT / "configurations.csv")
    # Diverse base algorithms plus all management modes, including market and limits.
    chosen = configurations.groupby("family", sort=False).head(2)
    chosen = pd.concat([chosen, configurations.groupby("management", sort=False).head(2)]).drop_duplicates("id")
    chosen[PARAMS].to_csv(BUILD / "verify_params.csv", index=False)
    run_engine(BUILD / "verify_params.csv", OUT / "verify_raw.csv", detail=OUT / "verify_detail")
    data = read_binary()
    f = pd.read_pickle(BUILD / "features.pkl")
    np.testing.assert_array_equal(data[0], f.index.as_unit("s").asi8)
    checks, total = [], 0
    for p in chosen.to_dict("records"):
        expected = reference(data, p)
        actual = pd.read_csv(OUT / f"verify_detail_{p['id']}.csv")
        if expected.empty and actual.empty:
            continue
        self_cols = ["id", "signal_i", "d", "fill_i", "exit_i", "outcome", "fold"]
        pd.testing.assert_frame_equal(expected[self_cols].reset_index(drop=True), actual[self_cols].reset_index(drop=True), check_dtype=False)
        numeric = ["entry", "sl", "tp", "fill_price", "exit_price", "r"]
        np.testing.assert_allclose(expected[numeric], actual[numeric], rtol=1e-10, atol=1e-8)
        total += len(actual)
        checks.append(dict(id=int(p["id"]), family=p["family"], setups=len(actual), filled=int((actual.fill_i >= 0).sum()), passed=True))
    result = dict(configuration_checks=checks, compared_setups=total, passed=True,
                  binary_timestamp_check=True, tolerance=1e-8)
    (OUT / "engine_verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Independent engine verification passed:", len(checks), "configs,", total, "setups", flush=True)


if __name__ == "__main__":
    verify()
