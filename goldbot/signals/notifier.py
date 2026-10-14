import json
import os
import urllib.parse
import urllib.request


def format_signal(s, symbol):
    arrow = "🟢 BUY" if s["direction"] == "BUY" else "🔴 SELL"
    return (
        f"{arrow} {symbol} (limit)\n"
        f"Entry: {s['entry']:.2f}\n"
        f"SL: {s['sl']:.2f}\n"
        f"TP: {s['tp']:.2f}  (R:R {s['rr']})\n"
        f"Setup: Asian sweep → CHoCH → {s['entry_model'].upper()} ({s['session']} KZ)\n"
        f"Valid until: {s['expiry_time']:%H:%M} UTC"
    )


class Notifier:
    def __init__(self, cfg):
        live = cfg["live"]
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN") or live.get("telegram_bot_token")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID") or live.get("telegram_chat_id")

    def send(self, text):
        print("\n" + text + "\n", flush=True)
        if not (self.token and self.chat_id):
            return
        data = urllib.parse.urlencode({"chat_id": self.chat_id, "text": text}).encode()
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            with urllib.request.urlopen(url, data=data, timeout=15) as r:
                if not json.load(r).get("ok"):
                    print("Telegram: send failed")
        except Exception as e:  # never let Telegram errors stop the bot
            print(f"Telegram error: {e}")
