"""Can filters or ML raise v2's win rate / accuracy?  python -m research.v2_improve

Base trades: Codex search_10k candidates #7940 (NY opening range) and #5361 (Bollinger re-entry),
exactly as executed by its verified engine (costs: spread 0.60, slippage 0.10).
Features are computed at the signal bar close only (no look-ahead).
Honest protocol: choose on TRAIN (2023-24), confirm on VALIDATION (2025), report TEST (2026) once.
"""
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from goldbot.config import load_config, resolve
from goldbot.data.store import load_m5, load_smt, resample
from goldbot.smc.indicators import atr
from goldbot.smc.sessions import session_frame
from goldbot.smc.structure import market_structure
from goldbot.strategy.asian_sweep import BAR, _Levels

warnings.filterwarnings("ignore")
CANDIDATES = {7940: "Opening range", 5361: "Bollinger re-entry"}
PERIOD = {0: "train", 1: "train", 2: "valid", 3: "valid", 4: "valid", 5: "valid", 6: "test", 7: "test"}


def _htf_trend(m5, tf):
    htf = resample(m5, tf)
    right = pd.DataFrame({"t": htf.index + pd.Timedelta(tf), "v": market_structure(htf, 2)["trend"].to_numpy()})
    return pd.merge_asof(pd.DataFrame({"t": m5.index + BAR}), right, on="t", direction="backward")["v"].fillna(0).to_numpy()


def market_features(m5, smt, cfg):
    """Per-M5-bar features, each known at that bar's close."""
    f = pd.DataFrame(index=m5.index)
    a = atr(m5, 14)
    f["atr"] = a
    f["atr_regime"] = a / a.rolling(288 * 5).mean()
    f["h4"] = _htf_trend(m5, "4h")
    f["d1"] = _htf_trend(m5, "1D")
    ema50 = m5["close"].ewm(span=50, adjust=False).mean()
    f["ema50_dist"] = (m5["close"] - ema50) / a
    f["mom12"] = (m5["close"] - m5["close"].shift(12)) / a
    f["mom48"] = (m5["close"] - m5["close"].shift(48)) / a
    sess = session_frame(m5.index, cfg)
    f["ny_hour"] = sess["ny_hour"].to_numpy()
    f["weekday"] = sess["session_day"].dt.weekday.to_numpy()
    day = sess["session_day"].to_numpy()
    first = ~np.r_[False, day[1:] == day[:-1]]
    day_open = pd.Series(np.where(first, m5["open"], np.nan), index=m5.index).ffill()
    f["vs_day_open"] = (m5["close"] - day_open) / a
    lv = _Levels(m5, sess)
    pdh = lv.prev_day["high"].reindex(day).to_numpy()
    pdl = lv.prev_day["low"].reindex(day).to_numpy()
    f["in_prev_range"] = (m5["close"].to_numpy() - pdl) / np.where(pdh - pdl > 0, pdh - pdl, np.nan)
    ah = lv.asian["asian_high"].reindex(day).to_numpy()
    al = lv.asian["asian_low"].reindex(day).to_numpy()
    after_asia = ~sess["asian"].to_numpy()
    run_lo = pd.Series(np.where(after_asia, m5["low"], np.nan)).groupby(day).cummin().to_numpy()
    run_hi = pd.Series(np.where(after_asia, m5["high"], np.nan)).groupby(day).cummax().to_numpy()
    f["asian_low_swept"] = (run_lo < al).astype(float)
    f["asian_high_swept"] = (run_hi > ah).astype(float)
    if smt is not None:
        f["silver_h1"] = _htf_trend(smt.reindex(m5.index).ffill().dropna(), "1h") if False else 0.0
        sv = smt.reindex(m5.index).ffill()
        f["silver_mom12"] = (sv["close"] - sv["close"].shift(12)) / sv["close"].rolling(288).std()
    return f


def trades_with_features(k, m5, mf):
    p = pd.read_csv(resolve(f"tests/fixtures/v2_reference/candidate_{k}_price_values.csv"))
    p = p[p["included_in_fold_metrics"] & (p["fill_i"] >= 0)].copy()
    p["period"] = p["fold"].map(PERIOD)
    d = p["d"].to_numpy()
    x = mf.iloc[p["signal_i"]].reset_index(drop=True)
    p = p.reset_index(drop=True)
    X = pd.DataFrame({
        "h1_bos": p["known_h1_bos"] * d, "h1_hhhl": p["known_h1_hhhl"] * d,
        "m15_bos": p["known_m15_bos"] * d, "m15_hhhl": p["known_m15_hhhl"] * d,
        "m5_trend": p["known_s2_trend"] * d, "h4_trend": x["h4"] * d, "d1_trend": x["d1"] * d,
        "rsi_dir": (p["known_rsi"] - 50) * d, "adx": p["known_adx"], "body": p["known_body"],
        "vol_ratio": p["known_volratio"], "atr_regime": x["atr_regime"],
        "risk_atr": p["planned_risk_usd_per_oz"] / p["known_atr"],
        "ema50_dist": x["ema50_dist"] * d, "mom12": x["mom12"] * d, "mom48": x["mom48"] * d,
        "vs_day_open": x["vs_day_open"] * d, "in_prev_range": np.where(d == 1, x["in_prev_range"], 1 - x["in_prev_range"]),
        "liq_swept_against": np.where(d == 1, x["asian_low_swept"], x["asian_high_swept"]),
        "liq_swept_with": np.where(d == 1, x["asian_high_swept"], x["asian_low_swept"]),
        "ny_hour": x["ny_hour"], "weekday": x["weekday"], "is_buy": (d == 1).astype(float),
    })
    if "silver_mom12" in x:
        X["silver_agree"] = x["silver_mom12"] * d
    return p, X.fillna(0.0)


def stats(r):
    r = np.asarray(r, float)
    if len(r) == 0:
        return dict(n=0, win=0.0, avgR=0.0, totR=0.0, PF=0.0)
    loss = -r[r < 0].sum()
    return dict(n=len(r), win=round(100 * (r > 0).mean(), 1), avgR=round(r.mean(), 3), totR=round(r.sum(), 1),
                PF=round(r[r > 0].sum() / loss, 2) if loss else 99.0)


def rule_filters(p, X):
    """Single-feature rules chosen on TRAIN; kept only if they also improve VALIDATION."""
    r, per = p["r"].to_numpy(), p["period"].to_numpy()
    base_tr, base_va = r[per == "train"].mean(), r[per == "valid"].mean()
    rows = []
    for col in X:
        v = X[col].to_numpy()
        tr = v[per == "train"]
        for q in (0.2, 0.33, 0.5, 0.67, 0.8):
            thr = np.quantile(tr, q)
            for side in (">=", "<"):
                keep = v >= thr if side == ">=" else v < thr
                m_tr, m_va, m_te = keep & (per == "train"), keep & (per == "valid"), keep & (per == "test")
                if m_tr.sum() < 40 or m_va.sum() < 20:
                    continue
                rows.append(dict(rule=f"{col} {side} {thr:.2f}", tr_avgR=r[m_tr].mean(), va_avgR=r[m_va].mean(),
                                 tr_keep=m_tr.mean() / (per == "train").mean(), **{f"test_{k}": val for k, val in stats(r[m_te]).items()},
                                 **{f"valid_{k}": val for k, val in stats(r[m_va]).items()}))
    df = pd.DataFrame(rows)
    good = df[(df["tr_avgR"] > base_tr + 0.05) & (df["va_avgR"] > base_va + 0.05)]
    return df, good.sort_values("tr_avgR", ascending=False)


def ml_walk_forward(p, X, model):
    """Train on all earlier periods, predict the next. Keep a trade if P(win) >= training win rate."""
    y = (p["r"] > 0).astype(int).to_numpy()
    per = p["period"].to_numpy()
    out = {}
    for test_name, train_names in [("valid", ["train"]), ("test", ["train", "valid"])]:
        tr, te = np.isin(per, train_names), per == test_name
        m = model()
        m.fit(X[tr], y[tr])
        prob = m.predict_proba(X[te])[:, 1]
        keep = prob >= y[tr].mean()
        auc = roc_auc_score(y[te], prob) if len(set(y[te])) > 1 else np.nan
        out[test_name] = dict(auc=round(auc, 3), all=stats(p["r"][te]), kept=stats(p["r"][te][keep]))
    return out


MODELS = {
    "logistic": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.3, max_iter=2000)),
    "boosting": lambda: GradientBoostingClassifier(n_estimators=150, max_depth=2, learning_rate=0.05, subsample=0.8, random_state=0),
}


def main():
    cfg = load_config()
    m5, smt = load_m5(cfg), load_smt(cfg)
    mf = market_features(m5, smt, cfg)
    pd.set_option("display.width", 240)
    pools = {}
    for k, name in CANDIDATES.items():
        p, X = trades_with_features(k, m5, mf)
        pools[k] = (p, X)
        print(f"\n################ #{k} {name}: {len(p)} trades")
        for per in ("train", "valid", "test"):
            print(f"  base {per:5s}: {stats(p['r'][p['period'] == per])}")
        df, good = rule_filters(p, X)
        print(f"  rule filters tested: {len(df)} | improve BOTH train and 2025 by >0.05R: {len(good)}")
        if len(good):
            cols = ["rule", "tr_keep", "tr_avgR", "va_avgR", "valid_win", "test_n", "test_win", "test_avgR", "test_PF"]
            print(good.head(8)[cols].round(3).to_string(index=False))
        for mname, model in MODELS.items():
            res = ml_walk_forward(p, X, model)
            for split, v in res.items():
                print(f"  ML {mname:8s} -> {split:5s} AUC {v['auc']} | all {v['all']} | ML-kept {v['kept']}")

    # pooled ML: both strategies together (more data), feature + strategy id
    p = pd.concat([pools[k][0].assign(src=k) for k in CANDIDATES], ignore_index=True)
    X = pd.concat([pools[k][1].assign(is_orb=float(k == 7940)) for k in CANDIDATES], ignore_index=True)
    print(f"\n################ POOLED v2 ({len(p)} trades)")
    for mname, model in MODELS.items():
        res = ml_walk_forward(p, X, model)
        for split, v in res.items():
            print(f"  ML {mname:8s} -> {split:5s} AUC {v['auc']} | all {v['all']} | ML-kept {v['kept']}")


if __name__ == "__main__":
    main()
