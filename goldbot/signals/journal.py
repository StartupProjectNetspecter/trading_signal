"""Automatic trade journal: every sent signal is followed on real MT5 prices until it closes.

The result is what you would get by following the signal exactly (same rules as the backtest
engine: spread, stop first on ambiguous candles, model-specific break-even / partial / max hold).
Also produces the 'My Results' text and the safety alerts.
"""
import json

import numpy as np
import pandas as pd

from goldbot.backtest.engine import simulate
from goldbot.config import resolve
from goldbot.signals.names import name
from goldbot.strategy import v2

JOURNAL = resolve("data/journal.csv")
ALERTS = resolve("data/journal_alerts.json")
COLS = ["key", "model", "signal_time", "expiry_time", "direction", "order", "entry", "sl", "tp", "rr",
        "status", "outcome", "r", "fill_time", "exit_time"]


def management(model, cfg):
    """v1 / v3 break-even, partial and max-hold (v2 trades are followed by the v2 engine itself)."""
    st, bt = cfg["strategy"], cfg["backtest"]
    if model == "v3":
        return dict(partial_at_r=None, breakeven_at_r=None, max_hold_bars=72)
    return dict(partial_at_r=st.get("partial_at_r"), partial_frac=st.get("partial_frac", 0.5),
                breakeven_at_r=st.get("breakeven_at_r"), max_hold_bars=bt["max_hold_bars"])


class Journal:
    def __init__(self, cfg):
        self.cfg = cfg
        self.df = self._load()

    def _load(self):
        if JOURNAL.exists():
            df = pd.read_csv(JOURNAL, parse_dates=["signal_time", "expiry_time", "fill_time", "exit_time"])
            for c in ("signal_time", "expiry_time", "fill_time", "exit_time"):
                df[c] = pd.to_datetime(df[c], utc=True)
            return df
        return pd.DataFrame(columns=COLS)

    def save(self):
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        self.df.to_csv(JOURNAL, index=False)

    def add(self, key, s):
        if key in set(self.df["key"]):
            return
        row = {c: s.get(c) for c in COLS}
        row.update(key=key, model=s.get("model", "v1"), order=s.get("order", "limit"), status="pending", outcome="", r=np.nan)
        self.df = pd.concat([self.df, pd.DataFrame([row])], ignore_index=True)
        self.save()

    def update(self, bars):
        """Re-evaluate every unfinished trade on the latest closed bars. Returns rows that just closed."""
        if self.df.empty:
            return []
        closed_now = []
        last_close = bars.index[-1] + pd.Timedelta(minutes=5)
        v2f = None
        for i, row in self.df[self.df["status"].isin(["pending", "open"])].iterrows():
            st = pd.Timestamp(row["signal_time"])
            if st < bars.index[0]:
                self.df.loc[i, ["status", "outcome"]] = ["unknown", "bot was offline"]
                continue
            if row["model"] in v2.MODELS:  # v2 trades use the v2 research engine itself
                v2f = v2f if v2f is not None else v2.features(bars, self.cfg)
                self._update_v2(i, row, bars, v2f, closed_now)
                continue
            mg = management(row["model"], self.cfg)
            cfg = {**self.cfg, "strategy": {**self.cfg["strategy"], **{k: v for k, v in mg.items() if k != "max_hold_bars"}},
                   "backtest": {**self.cfg["backtest"], "max_hold_bars": mg["max_hold_bars"]}}
            sig = pd.DataFrame([{k: row[k] for k in ("signal_time", "expiry_time", "direction", "entry", "sl", "tp", "rr", "order")}])
            t = simulate(sig, bars, cfg).iloc[0]
            if not t["filled"]:
                if pd.Timestamp(row["expiry_time"]) > last_close and t["outcome"] != "no_fill_cancelled":
                    continue  # still waiting for a fill
                self.df.loc[i, ["status", "outcome"]] = ["no_fill", t["outcome"].replace("no_fill_", "")]
                continue
            hold_end = t["fill_time"] + pd.Timedelta(minutes=5) * mg["max_hold_bars"]
            if t["outcome"].startswith("time") and hold_end > last_close:
                self.df.loc[i, ["status", "fill_time"]] = ["open", t["fill_time"]]
                continue
            self.df.loc[i, ["status", "outcome", "r", "fill_time", "exit_time"]] = ["closed", t["outcome"], t["r"], t["fill_time"], t["exit_time"]]
            closed_now.append(self.df.loc[i].to_dict())
        self.save()
        return closed_now

    def _update_v2(self, i, row, bars, f, closed_now):
        bar = bars.index.searchsorted(pd.Timestamp(row["signal_time"]) - pd.Timedelta(minutes=5))
        if bar >= len(bars) or bars.index[bar] + pd.Timedelta(minutes=5) != pd.Timestamp(row["signal_time"]):
            self.df.loc[i, ["status", "outcome"]] = ["unknown", "signal bar missing"]
            return
        expiry_bars = int(round((pd.Timestamp(row["expiry_time"]) - pd.Timestamp(row["signal_time"])) / pd.Timedelta(minutes=5)))
        res = v2.execute(f, bar, 1 if row["direction"] == "BUY" else -1, float(row["entry"]), float(row["sl"]), float(row["tp"]),
                         row["order"] == "market", expiry_bars, v2.MODELS[row["model"]])
        if res["outcome"] == "pending":
            return
        if res["outcome"] == "open":
            self.df.loc[i, ["status", "fill_time"]] = ["open", bars.index[res["fill_i"]]]
            return
        if res["fill_i"] < 0:
            self.df.loc[i, ["status", "outcome"]] = ["no_fill", res["outcome"]]
            return
        self.df.loc[i, ["status", "outcome", "r", "fill_time", "exit_time"]] = [
            "closed", res["outcome"], res["r"], bars.index[res["fill_i"]], bars.index[res["exit_i"]] + pd.Timedelta(minutes=5)]
        closed_now.append(self.df.loc[i].to_dict())

    # ---- reports --------------------------------------------------------
    def results_text(self, tz):
        df = self.df
        if df.empty:
            return "📒 No signals recorded yet. Results appear here automatically after each signal."
        closed = df[df["status"] == "closed"]
        lines = ["📒 My Results (live, if every signal was followed exactly)"]
        lines.append(f"Signals: {len(df)} · closed {len(closed)} · open {(df.status == 'open').sum()} · "
                     f"waiting {(df.status == 'pending').sum()} · not filled {(df.status == 'no_fill').sum()}")
        groups = [("All", closed)] + [(name(m), closed[closed["model"] == m]) for m in ("v1", "v2a", "v2b", "v3")]
        for label, g in groups:
            if len(g) == 0:
                continue
            r = g["r"].astype(float)
            loss = -r[r < 0].sum()
            pf = f"{r[r > 0].sum() / loss:.2f}" if loss else "∞"
            lines.append(f"{label}: {len(r)} trades · win {100 * (r > 0).mean():.0f}% · PF {pf} · {r.sum():+.2f}R")
        if len(closed):
            lines.append("\nLast closed:")
            for row in closed.sort_values("exit_time").tail(5).itertuples():
                t = pd.Timestamp(row.signal_time).tz_convert(tz)
                icon = "✅" if row.r > 0 else "➖" if row.r == 0 else "❌"
                lines.append(f"{icon} [{name(row.model)}] {t:%d %b %H:%M} {row.direction} {row.outcome} {row.r:+.2f}R")
        lines.append("\nBacktest reference: ~52% win rate, PF ~1.45. Judge after 20+ trades.")
        return "\n".join(lines)

    def safety_alerts(self):
        """New warnings when live results drift far from the backtest. Each alert is sent once."""
        live = self.cfg["live"]
        closed = self.df[(self.df["status"] == "closed") & (self.df["model"] != "v3")].sort_values("exit_time")  # Dip Buy (still in test) excluded
        if closed.empty:
            return []
        r = closed["r"].astype(float).to_numpy()
        streak = 0
        for x in r[::-1]:
            if x < 0:
                streak += 1
            else:
                break
        cum = np.cumsum(r)
        peak = np.maximum.accumulate(np.r_[0, cum])[1:]
        dd = float((peak - cum)[-1])
        peak_at = int(np.flatnonzero(cum >= peak)[-1]) if (cum >= peak).any() else -1  # start of this drawdown episode
        loss = -r[r < 0].sum()
        pf = r[r > 0].sum() / loss if loss else 99
        checks = {
            f"streak@{len(r) - streak}": (streak >= live.get("alert_losing_streak", 6),
                                f"⚠️ SAFETY: {streak} losses in a row (backtest worst was 4). Consider pausing or halving risk."),
            f"dd@{peak_at}": (dd >= live.get("alert_drawdown_r", 8),
                             f"⚠️ SAFETY: live drawdown is {dd:.1f}R (backtest worst ~6R). Consider pausing until reviewed."),
            "pf_low": (len(r) >= live.get("alert_min_trades", 20) and pf < 0.9,
                       f"⚠️ SAFETY: after {len(r)} trades the live profit factor is {pf:.2f} (backtest ~1.45). The edge may be gone - stop and review."),
        }
        try:
            sent = set(json.loads(ALERTS.read_text()))
        except (FileNotFoundError, ValueError):
            sent = set()
        out = []
        for key, (hit, msg) in checks.items():
            if hit and key not in sent:
                out.append(msg)
                sent.add(key)
        if not checks["pf_low"][0]:
            sent.discard("pf_low")
        ALERTS.write_text(json.dumps(sorted(sent)))
        return out
