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
from goldbot.signals import notifier as tg
from goldbot.signals.status import market_status
from goldbot.strategy.asian_sweep import generate_signals

STATE = resolve("data/live_state.json")
LOG = resolve("data/signals_log.csv")
TRADES = resolve("reports/trades.csv")


def load_sent():
    try:
        return set(json.loads(STATE.read_text()))
    except (FileNotFoundError, ValueError):
        return set()


def save_sent(sent):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(sorted(sent)[-500:]))


def log_signal(s):
    row = pd.DataFrame([{k: s[k] for k in ("signal_time", "direction", "entry", "sl", "tp", "rr", "liquidity", "expiry_time")}])
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
        self.signals = generate_signals(bars, self.cfg, self.smt)
        self.alert_new()
        print(f"{pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC  checked bar {bars.index[-1]:%H:%M}  price {bars['close'].iat[-1]:.2f}")
        return True

    def alert_new(self):
        now = pd.Timestamp.now(tz="UTC")
        for s in self.signals.to_dict("records") if len(self.signals) else []:
            key = f"{s['signal_time']:%Y%m%d%H%M}_{s['direction']}"
            if key in self.sent or s["expiry_time"] <= now:
                continue
            self.tg.send(tg.format_signal(s, self.sym, self.tz_local))
            log_signal(s)
            self.sent.add(key)
            save_sent(self.sent)

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
                text = "✅ Valid setup right now:\n\n" + tg.format_signal(a, self.sym, self.tz_local)
            else:
                text = (
                    "⏳ No valid setup right now.\n"
                    "A real signal needs: liquidity sweep → CHoCH → order block inside the kill zone.\n"
                    "You will be alerted automatically the moment one forms.\n\n" + self.status_text()
                )
        elif action == "status":
            text = self.status_text()
        elif action == "last":
            text = self.last_signals()
        elif action == "stats":
            text = self.performance()
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

    def last_signals(self, n=5):
        if not LOG.exists():
            return "📜 No live signals sent yet."
        df = pd.read_csv(LOG, parse_dates=["signal_time"]).tail(n)
        lines = [f"📜 Last {len(df)} signals"]
        for r in df.itertuples():
            t = pd.Timestamp(r.signal_time).tz_convert(self.tz_local)
            icon = "🟢" if r.direction == "BUY" else "🔴"
            lines.append(f"{icon} {t:%d %b %H:%M} {r.direction} @ {r.entry:.2f}  SL {r.sl:.2f}  TP {r.tp:.2f}")
        return "\n".join(lines)

    def performance(self):
        if not TRADES.exists():
            return "📊 No backtest report yet. Run: python run_backtest.py"
        t = pd.read_csv(TRADES, parse_dates=["signal_time", "exit_time"])
        bt = self.cfg["backtest"]
        s = stats(t, bt["risk_per_trade"], bt["initial_equity"])
        start, end = t["signal_time"].min(), t["signal_time"].max()
        return (
            f"📊 Backtest {start:%b %Y} – {end:%b %Y}\n"
            f"Trades: {s['trades']}\n"
            f"Win rate: {s['win_rate_%']}%\n"
            f"Profit factor: {s['profit_factor']}\n"
            f"Total: {s['total_R']:+}R ({s['return_%']:+}% at {bt['risk_per_trade']:.0%} risk)\n"
            f"Max drawdown: {s['max_drawdown_%']}%\n"
            f"Longest losing streak: {s['max_losing_streak']}\n\n"
            "Simulation on real historical prices. Live results will differ."
        )

    # ---- main loop -------------------------------------------------------
    def run(self):
        self.tg.setup()
        print(f"Connected to MT5. Symbol={self.sym}, server tz={self.server_tz}. Telegram={'on' if self.tg.enabled else 'off'}")
        print("Watching for setups... (Ctrl+C to stop)")
        self.tg.send("🤖 Gold signal bot started. Watching XAUUSD for setups.")
        poll = self.cfg["live"]["poll_seconds"]
        while True:
            self.refresh()
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
