import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def stats(trades, risk_per_trade=0.01, initial=10000):
    t = trades[trades["filled"]].sort_values("exit_time")
    if t.empty:
        return {"trades": 0}
    r = t["r"].to_numpy()
    cum = np.cumsum(r)
    dd_r = (np.maximum.accumulate(np.r_[0, cum])[1:] - cum).max()
    equity = initial * np.cumprod(1 + risk_per_trade * r)
    peak = np.maximum.accumulate(np.r_[initial, equity])[1:]
    losses = r < 0
    streak = max((len(x) for x in "".join("L" if v else "W" for v in losses).split("W")), default=0)
    gross_loss = -r[r < 0].sum()
    return {
        "trades": len(r),
        "win_rate_%": round(100 * (r > 0).mean(), 1),
        "avg_R": round(r.mean(), 3),
        "total_R": round(r.sum(), 1),
        "profit_factor": round(r[r > 0].sum() / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "max_drawdown_R": round(dd_r, 1),
        "max_losing_streak": streak,
        "return_%": round(100 * (equity[-1] / initial - 1), 1),
        "max_drawdown_%": round(100 * ((peak - equity) / peak).max(), 1),
    }


def _table(title, groups, bt):
    lines = [f"\n== {title} =="]
    rows = {k: stats(g, bt["risk_per_trade"], bt["initial_equity"]) for k, g in groups}
    df = pd.DataFrame(rows).T
    lines.append(df.to_string() if not df.empty else "(none)")
    return lines


def write_report(trades, m5, cfg, out_dir):
    bt = cfg["backtest"]
    out_dir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(out_dir / "trades.csv", index=False)

    split = m5.index[0] + (m5.index[-1] - m5.index[0]) * (1 - bt["oos_fraction"])
    filled = trades[trades["filled"]].copy() if len(trades) else trades
    lines = [
        f"{cfg['symbol']} SMC/ICT backtest  {m5.index[0]:%Y-%m-%d} -> {m5.index[-1]:%Y-%m-%d}",
        f"Signals: {len(trades)}   filled: {int(trades['filled'].sum()) if len(trades) else 0}",
    ]
    if len(trades):
        lines.append("Outcomes: " + ", ".join(f"{k}={v}" for k, v in trades["outcome"].value_counts().items()))
    lines += _table("Overall", [("all", trades)], bt)
    if len(trades):
        is_oos = np.where(trades["signal_time"] < split, "in-sample", "out-of-sample")
        lines += _table(f"In-sample vs out-of-sample (split {split:%Y-%m-%d})", trades.groupby(is_oos), bt)
        lines += _table("By session", trades.groupby("session"), bt)
        lines += _table("By direction", trades.groupby("direction"), bt)
        lines += _table("By entry model", trades.groupby("entry_model"), bt)
        if "liquidity" in trades:
            lines += _table("By liquidity swept", trades.groupby("liquidity"), bt)
        if "smt" in trades:
            lines += _table("By SMT divergence (silver)", trades.groupby("smt"), bt)
        lines += _table("By year", trades.groupby(trades["signal_time"].dt.year), bt)

    text = "\n".join(lines)
    (out_dir / "summary.txt").write_text(text, encoding="utf-8")
    if len(filled):
        _plot(filled, bt, out_dir / "equity.png", split)
    return text


def _plot(filled, bt, path, split):
    t = filled.sort_values("exit_time")
    equity = bt["initial_equity"] * np.cumprod(1 + bt["risk_per_trade"] * t["r"].to_numpy())
    monthly = t.groupby(t["exit_time"].dt.tz_localize(None).dt.to_period("M"))["r"].sum()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={"height_ratios": [2, 1]})
    ax1.plot(t["exit_time"], equity, color="#b8860b", lw=1.6)
    ax1.axvline(split, color="grey", ls="--", lw=1)
    ax1.text(split, ax1.get_ylim()[1], " out-of-sample →", va="top", color="grey")
    ax1.set_title(f"SMC/ICT equity ({bt['risk_per_trade']:.0%} risk per trade)")
    ax1.set_ylabel("Equity ($)")
    ax1.grid(alpha=0.3)
    colors = ["#2e8b57" if v >= 0 else "#c0392b" for v in monthly]
    ax2.bar(monthly.index.astype(str), monthly.to_numpy(), color=colors)
    ax2.set_ylabel("R per month")
    ax2.tick_params(axis="x", rotation=60, labelsize=8)
    ax2.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
