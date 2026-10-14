"""Live signal bot: reads closed M5 bars from MT5 and alerts new setups (console + Telegram).

It only SENDS SIGNALS. It never places orders.

    python run_live.py
"""
import json
import time

import pandas as pd

from goldbot.config import load_config, resolve
from goldbot.data import mt5_source
from goldbot.signals.notifier import Notifier, format_signal
from goldbot.strategy.asian_sweep import generate_signals

STATE = resolve("data/live_state.json")


def load_sent():
    try:
        return set(json.loads(STATE.read_text()))
    except (FileNotFoundError, ValueError):
        return set()


def save_sent(sent):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(sorted(sent)[-500:]))


def main():
    cfg = load_config()
    sym = cfg["data"]["mt5_symbol"]
    live = cfg["live"]
    notifier = Notifier(cfg)
    mt5_source.connect(sym)
    if cfg["strategy"].get("smt_symbol"):
        mt5_source.connect(cfg["strategy"]["smt_symbol"])
    tz = mt5_source.resolve_server_tz(sym, cfg["data"]["mt5_server_tz"])
    print(f"Connected to MT5. Symbol={sym}, server tz={tz}. Watching for setups... (Ctrl+C to stop)")

    sent = load_sent()
    last_bar = None
    try:
        while True:
            bars = mt5_source.latest_closed_bars(sym, "M5", live["lookback_days"] * 288, tz)
            if bars.index[-1] != last_bar:
                last_bar = bars.index[-1]
                smt = None
                if cfg["strategy"].get("smt_symbol"):
                    smt = mt5_source.latest_closed_bars(cfg["strategy"]["smt_symbol"], "M5", live["lookback_days"] * 288, tz)
                signals = generate_signals(bars, cfg, smt)
                now = pd.Timestamp.now(tz="UTC")
                for s in signals.to_dict("records") if len(signals) else []:
                    key = f"{s['signal_time']:%Y%m%d%H%M}_{s['direction']}"
                    if key in sent or s["expiry_time"] <= now:
                        continue
                    notifier.send(format_signal(s, sym))
                    sent.add(key)
                    save_sent(sent)
                print(f"{now:%Y-%m-%d %H:%M} UTC  checked bar {last_bar:%H:%M}  price {bars['close'].iat[-1]:.2f}")
            time.sleep(live["poll_seconds"])
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        mt5_source.shutdown()


if __name__ == "__main__":
    main()
