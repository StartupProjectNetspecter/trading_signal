"""Live signal bot: reads closed M5 bars from MT5, alerts new setups on Telegram and answers the
menu buttons (Signal Now, Market Status, Last Signals, Performance, ...).

It only SENDS SIGNALS. It never places orders.

    python run_live.py
"""
import json
import time

import pandas as pd

from goldbot.backtest.report import stats
from goldbot.config import load_config, resolve
from goldbot.data import mt5_source
from goldbot.signals import daily_plan
from goldbot.signals import notifier as tg
from goldbot.signals.journal import Journal
from goldbot.signals.names import MODES, get_mode, mode_text, name, set_mode
from goldbot.signals.risk import lot_line
from goldbot.signals.status import market_status
from goldbot.strategy.asian_sweep import generate_signals
from goldbot.strategy.v2 import generate_v2
from goldbot.strategy.v3 import generate_v3
from goldbot.signals.setup_alerts import new_alerts

STATE = resolve("data/live_state.json")
LOG = resolve("data/signals_log.csv")
TRADES = resolve("reports/trades.csv")
V2_TRADES = resolve("reports/v2_trades.csv")
V3_TRADES = resolve("reports/v3_trades.csv")


def load_sent():
    try:
        return set(json.loads(STATE.read_text()))
    except (FileNotFoundError, ValueError):
        return set()


def save_sent(sent):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(sorted(sent)[-500:]))


def log_signal(s):
    row = pd.DataFrame([{k: s.get(k) for k in ("signal_time", "model", "direction", "entry", "sl", "tp", "rr", "liquidity", "expiry_time")}])
    row.to_csv(LOG, mode="a", header=not LOG.exists(), index=False)


class LiveBot:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sym = cfg["data"]["mt5_symbol"]
        self.smt_sym = cfg["strategy"].get("smt_symbol")
        self.tz_local = cfg["live"].get("display_tz", "Asia/Phnom_Penh")
        self.bars = self.smt = None
        self.signals = pd.DataFrame()
        self.tg = tg.Notifier(cfg)
        self.sent = load_sent()
        self.journal = Journal(cfg)
        mt5_source.connect(self.sym)
        if self.smt_sym:
            mt5_source.connect(self.smt_sym)
        self.server_tz = mt5_source.resolve_server_tz(self.sym, cfg["data"]["mt5_server_tz"])

    def refresh(self):
        """Fetch the latest closed bars and recompute signals. Returns True when a new bar arrived."""
        n = self.cfg["live"]["lookback_days"] * 288
        bars = mt5_source.latest_closed_bars(self.sym, "M5", n, self.server_tz)
        if self.bars is not None and bars.index[-1] == self.bars.index[-1]:
            return False
        self.bars = bars
        self.smt = mt5_source.latest_closed_bars(self.smt_sym, "M5", n, self.server_tz) if self.smt_sym else None
        models = MODES[get_mode(self.cfg)]["models"]
        frames = []
        if "v1" in models:
            v1 = generate_signals(bars, self.cfg, self.smt)
            if len(v1):
                frames.append(v1.assign(model="v1"))
        if "v2a" in models or "v2b" in models:
            v2 = generate_v2(bars, self.cfg)
            if len(v2):
                frames.append(v2[v2["model"].isin(models)])
        if "v3" in models:
            v3 = generate_v3(bars, self.cfg)
            if len(v3):
                frames.append(v3)
        self.signals = pd.concat(frames, ignore_index=True).sort_values("signal_time") if frames else pd.DataFrame()
        self.alert_new()
        self.track_results()
        if self.cfg["live"].get("setup_alerts", True):
            for msg in new_alerts(bars, self.cfg):
                self.tg.send(msg)
        print(f"{pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC  checked bar {bars.index[-1]:%H:%M}  price {bars['close'].iat[-1]:.2f}")
        return True

    def alert_new(self):
        now = pd.Timestamp.now(tz="UTC")
        for s in self.signals.to_dict("records") if len(self.signals) else []:
            model = s.get("model", "v1")
            key = f"{s['signal_time']:%Y%m%d%H%M}_{s['direction']}" + ("" if model == "v1" else f"_{model}")
            if key in self.sent or s["expiry_time"] <= now:
                continue
            self.tg.send(self.signal_text(s))
            log_signal(s)
            self.journal.add(key, s)
            self.sent.add(key)
            save_sent(self.sent)

    def signal_text(self, s):
        risk = self.cfg["live"].get("risk_per_trade", 0.01)
        lots = lot_line(s["entry"], s["sl"], mt5_source.account(), risk, mt5_source.symbol_specs(self.sym))
        return tg.format_signal(s, self.sym, self.tz_local) + "\n" + lots

    def track_results(self):
        """Follow every journaled signal on real prices; report closed trades and safety alerts."""
        for row in self.journal.update(self.bars):
            icon = "✅" if row["r"] > 0 else "➖" if row["r"] == 0 else "❌"
            t = pd.Timestamp(row["signal_time"]).tz_convert(self.tz_local)
            self.tg.send(f"{icon} Result [{name(row['model'])}] {row['direction']} from {t:%d %b %H:%M}: "
                         f"{row['outcome']} {row['r']:+.2f}R\n(entry {row['entry']:.2f}, SL {row['sl']:.2f}, TP {row['tp']:.2f})")
        for msg in self.journal.safety_alerts():
            self.tg.send(msg)

    def active_signal(self):
        if self.signals.empty:
            return None
        live = self.signals[self.signals["expiry_time"] > pd.Timestamp.now(tz="UTC")]
        return live.iloc[-1].to_dict() if len(live) else None

    def status_text(self):
        return market_status(self.bars, self.smt, self.cfg, mt5_source.current_tick(self.sym), self.active_signal())

    # ---- button actions -------------------------------------------------
    def reply(self, chat, action):
        if action in ("signal", "status"):
            self.refresh()
        if action == "signal":
            a = self.active_signal()
            if a:
                text = "✅ Valid setup right now:\n\n" + self.signal_text(a)
            else:
                text = (
                    "⏳ No valid setup right now.\n"
                    f"Mode {MODES[get_mode(self.cfg)]['label']}: watching "
                    + ", ".join(name(m) for m in MODES[get_mode(self.cfg)]["models"]) + ".\n"
                    "You will be alerted automatically the moment one forms.\n\n" + self.status_text()
                )
        elif action == "status":
            text = self.status_text()
        elif action == "last":
            text = self.last_signals()
        elif action == "stats":
            text = self.performance()
        elif action == "results":
            text = self.journal.results_text(self.tz_local)
        elif action == "plan":
            self.refresh()
            text = self.plan()
        elif action == "mode":
            self.tg.send(mode_text(get_mode(self.cfg)), chat, buttons=tg.MODE_KEYBOARD)
            return
        elif action == "menu":
            text = "Main menu 👇"
        elif action and action.startswith("set_mode:"):
            key = action.split(":", 1)[1]
            set_mode(key)
            self.bars = None  # recompute signals for the new mode on the next check
            text = f"✅ Mode changed to {MODES[key]['label']}\n{MODES[key]['summary']}"
        elif action == "help":
            text = tg.HOW_TO
        elif action == "about":
            text = tg.ABOUT
        elif action == "privacy":
            text = tg.PRIVACY
        elif action == "start":
            text = "👋 Welcome!\n\n" + tg.ABOUT + "\n\nUse the buttons below."
        else:
            text = "Please use the buttons below. 👇"
        self.tg.send(text, chat)

    def plan(self):
        return daily_plan.plan_text(self.bars, self.smt, self.cfg, mt5_source.current_tick(self.sym), self.active_signal())

    def last_signals(self, n=5):
        if not LOG.exists():
            return "📜 No live signals sent yet."
        df = pd.read_csv(LOG, parse_dates=["signal_time"]).tail(n)
        lines = [f"📜 Last {len(df)} signals"]
        for r in df.itertuples():
            t = pd.Timestamp(r.signal_time).tz_convert(self.tz_local)
            icon = "🟢" if r.direction == "BUY" else "🔴"
            model = getattr(r, "model", None)
            tag = f"[{str(model).upper()}] " if isinstance(model, str) else ""
            lines.append(f"{icon} {tag}{t:%d %b %H:%M} {r.direction} @ {r.entry:.2f}  SL {r.sl:.2f}  TP {r.tp:.2f}")
        return "\n".join(lines)

    def performance(self):
        if not TRADES.exists():
            return "📊 No backtest report yet. Run: python run_backtest.py"
        bt = self.cfg["backtest"]
        t = pd.read_csv(TRADES, parse_dates=["signal_time", "exit_time"])
        start, end = t["signal_time"].min(), t["signal_time"].max()
        weeks = max((end - start).days / 7, 1)
        sets = [(name("v1"), t)]
        if V2_TRADES.exists():
            v2 = pd.read_csv(V2_TRADES, parse_dates=["signal_time", "exit_time"])
            sets += [(name("v2a"), v2[v2["model"] == "v2a"]), (name("v2b"), v2[v2["model"] == "v2b"])]
        if V3_TRADES.exists():
            sets.append((name("v3") + " (at $0.30 spread)", pd.read_csv(V3_TRADES, parse_dates=["signal_time", "exit_time"])))
        lines = [f"📊 Backtest {start:%b %Y} – {end:%b %Y}"]
        for label, df in sets:
            s = stats(df, bt["risk_per_trade"], bt["initial_equity"])
            if not s.get("trades"):
                continue
            lines.append(
                f"\n{label}: {s['trades']} trades ({s['trades'] / weeks:.1f}/week)\n"
                f"  Win rate {s['win_rate_%']}% · PF {s['profit_factor']} · {s['total_R']:+}R · max DD {s['max_drawdown_%']}%"
            )
        lines.append("\nSimulation on real historical prices. Live results will differ.")
        return "\n".join(lines)

    # ---- main loop -------------------------------------------------------
    def run(self):
        self.tg.setup()
        print(f"Connected to MT5. Symbol={self.sym}, server tz={self.server_tz}. Telegram={'on' if self.tg.enabled else 'off'}")
        print("Watching for setups... (Ctrl+C to stop)")
        mode = MODES[get_mode(self.cfg)]
        self.tg.send(f"🤖 Gold signal bot started - mode {mode['label']}\n"
                     f"Watching: {', '.join(name(m) for m in mode['models'])}.\nChange it any time with ⚙️ Mode.")
        poll = self.cfg["live"]["poll_seconds"]
        while True:
            try:
                self.refresh()
            except Exception as e:  # MT5 disconnected / no data: keep the bot alive and retry
                print(f"{pd.Timestamp.now(tz='UTC'):%H:%M} UTC  MT5 data error: {e}. Retrying in {poll}s...", flush=True)
                time.sleep(poll)
                continue
            if self.tg.enabled and daily_plan.due(self.cfg):
                self.tg.send(self.plan())
                daily_plan.mark_sent(self.cfg)
            # long-poll Telegram: returns immediately when a button is pressed
            for chat, action in self.tg.poll(poll):
                self.reply(chat, action)
            if not self.tg.enabled:
                time.sleep(poll)


def main():
    bot = LiveBot(load_config())
    try:
        bot.run()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        mt5_source.shutdown()


if __name__ == "__main__":
    main()
