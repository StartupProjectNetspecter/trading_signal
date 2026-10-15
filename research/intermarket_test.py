"""Do the markets professional gold traders watch improve our signals?  python -m research.intermarket_test

Dollar (EURUSD), US yields proxy (USDJPY), stock-market mood (US500) and silver (XAGUSD), all M5 from MT5.
Features are computed at the gold signal bar close (other markets forward-filled = last known bar).
Protocol: choose filter on TRAIN (2023-24), require it to also improve VALIDATION (2025), report TEST (2026).
Trade sets: v1 (live strategy), v2 raw pool (#7940 + #5361), v2 filtered (volume / ADX filters).
"""
import numpy as np
import pandas as pd

from goldbot.config import load_config, resolve
from goldbot.data.store import load_m5, load_smt, resample
from goldbot.smc.structure import market_structure
from goldbot.strategy.asian_sweep import BAR
from research.v2_improve import market_features, stats, trades_with_features

# sign: +1 if the market usually moves WITH gold, -1 if AGAINST gold
MARKETS = {"EURUSD": 1, "USDJPY": -1, "US500": 0, "XAGUSD": 1}


def _h1_trend(df, index):
    h1 = resample(df, "1h")
    right = pd.DataFrame({"t": h1.index + pd.Timedelta("1h"), "v": market_structure(h1, 2)["trend"].to_numpy()})
    return pd.merge_asof(pd.DataFrame({"t": index + BAR}), right, on="t", direction="backward")["v"].fillna(0).to_numpy()


def intermarket_features(m5, cfg):
    g = m5["close"]
    g_ret = g.pct_change()
    out = pd.DataFrame(index=m5.index)
    for sym in MARKETS:
        x = load_m5(cfg, sym)
        xa = x.reindex(m5.index, method="ffill")  # last known bar of the other market
        c = xa["close"]
        vol = c.pct_change().rolling(288).std()
        for k in (12, 48):
            out[f"{sym}_mom{k}"] = c.pct_change(k) / (vol * np.sqrt(k))
        out[f"{sym}_h1"] = _h1_trend(x, m5.index)
        out[f"{sym}_corr"] = g_ret.rolling(288).corr(c.pct_change())
        # SMT-style divergence over the last 24 bars: gold breaks its 24-bar low/high, the other market does not
        g_new_low = m5["low"] < m5["low"].shift(1).rolling(24).min()
        g_new_high = m5["high"] > m5["high"].shift(1).rolling(24).max()
        sgn = MARKETS[sym] or 1
        x_low_eq = (xa["low"] < xa["low"].shift(1).rolling(24).min()) if sgn == 1 else (xa["high"] > xa["high"].shift(1).rolling(24).max())
        x_high_eq = (xa["high"] > xa["high"].shift(1).rolling(24).max()) if sgn == 1 else (xa["low"] < xa["low"].shift(1).rolling(24).min())
        out[f"{sym}_bull_div"] = (g_new_low.rolling(6).max().astype(bool) & ~x_low_eq.rolling(6).max().astype(bool)).astype(float)
        out[f"{sym}_bear_div"] = (g_new_high.rolling(6).max().astype(bool) & ~x_high_eq.rolling(6).max().astype(bool)).astype(float)
    return out


def directional(im, idx, d):
    """Turn per-bar intermarket values into 'agrees with the gold trade' features."""
    x = im.iloc[idx].reset_index(drop=True)
    f = pd.DataFrame(index=x.index)
    for sym, sgn in MARKETS.items():
        s = sgn if sgn else 1  # US500: sign unknown -> rules may pick either side
        for k in (12, 48):
            f[f"{sym}_mom{k}_agree"] = x[f"{sym}_mom{k}"] * s * d
        f[f"{sym}_h1_agree"] = x[f"{sym}_h1"] * s * d
        f[f"{sym}_corr"] = x[f"{sym}_corr"] * s
        f[f"{sym}_div"] = np.where(d == 1, x[f"{sym}_bull_div"], x[f"{sym}_bear_div"])
    return f.fillna(0.0)


def filters_report(name, r, period, F):
    r, period = np.asarray(r, float), np.asarray(period)
    base = {p: stats(r[period == p]) for p in ("train", "valid", "test")}
    print(f"\n### {name}: {len(r)} trades")
    for p, s in base.items():
        print(f"  base {p:5s}: n {s['n']:3d} win {s['win']:5.1f}% PF {s['PF']:5.2f} avgR {s['avgR']:+.3f}")
    rows = []
    for col in F:
        v = F[col].to_numpy()
        tr = v[period == "train"]
        thresholds = sorted(set([0.0] + [float(np.quantile(tr, q)) for q in (0.33, 0.5, 0.67)]))
        for thr in thresholds:
            for side in (">", "<="):
                keep = v > thr if side == ">" else v <= thr
                n_tr, n_va = (keep & (period == "train")).sum(), (keep & (period == "valid")).sum()
                if n_tr < max(15, 0.4 * (period == "train").sum()) or n_va < 10:
                    continue
                s = {p: stats(r[keep & (period == p)]) for p in ("train", "valid", "test")}
                rows.append(dict(rule=f"{col} {side} {thr:.2f}", **{f"{p}_{k}": s[p][k] for p in s for k in ("n", "win", "avgR", "PF")}))
    df = pd.DataFrame(rows).drop_duplicates("rule")
    good = df[(df["train_avgR"] > base["train"]["avgR"] + 0.05) & (df["valid_avgR"] > base["valid"]["avgR"] + 0.05)]
    held = good[good["test_avgR"] > base["test"]["avgR"]]
    print(f"  intermarket rules tested: {len(df)} | improve train AND 2025: {len(good)} | ALSO improve 2026: {len(held)}")
    if len(good):
        cols = ["rule", "train_n", "train_win", "train_PF", "valid_win", "valid_PF", "test_n", "test_win", "test_PF"]
        print(good.sort_values("train_avgR", ascending=False).head(10)[cols].to_string(index=False))
    return df, good, held


def main():
    cfg = load_config()
    m5 = load_m5(cfg)
    im = intermarket_features(m5, cfg)
    pd.set_option("display.width", 220)
    results = {}

    # v1 live strategy
    t = pd.read_csv(resolve("reports/trades.csv"), parse_dates=["signal_time"])
    t = t[t["filled"]].reset_index(drop=True)
    idx = m5.index.searchsorted(t["signal_time"] - BAR)
    d = np.where(t["direction"] == "BUY", 1, -1)
    period = np.where(t["signal_time"] < "2025-01-01", "train", np.where(t["signal_time"] < "2026-01-01", "valid", "test"))
    results["v1"] = filters_report("v1 (live strategy)", t["r"], period, directional(im, idx, d))

    # v2 trades from the Codex engine
    mf = market_features(m5, load_smt(cfg), cfg)
    raw, filt = [], []
    for k, col, thr in [(7940, "vol_ratio", 1.34), (5361, "adx", 30.61)]:
        p, X = trades_with_features(k, m5, mf)
        raw.append(p)
        filt.append(p[(X[col] >= thr).to_numpy()])
    for name, pool in [("v2 raw pool (#7940 + #5361)", pd.concat(raw, ignore_index=True)),
                       ("v2 filtered (volume / ADX)", pd.concat(filt, ignore_index=True))]:
        F = directional(im, pool["signal_i"].to_numpy(), pool["d"].to_numpy())
        results[name] = filters_report(name, pool["r"], pool["period"], F)
    return results


if __name__ == "__main__":
    main()
