"""Telegram: signal alerts, bot profile (description + commands) and the button menu."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

ABOUT = (
    "🥇 Gold (XAUUSD) signal bot using ICT / Smart Money Concepts.\n\n"
    "It watches the New York session for a liquidity sweep (Asian or London high/low), "
    "a change of character (CHoCH) and an order block entry, then sends Entry, SL and TP.\n\n"
    "Backtest Jan 2023 – Oct 2026: 53% win rate, profit factor 1.38, max drawdown 6%.\n"
    "Signals only — it never places trades. Past results do not guarantee future results. Not financial advice."
)
SHORT_ABOUT = "XAUUSD ICT/SMC signals: liquidity sweep → CHoCH → order block, New York session. Signals only, not financial advice."
HOW_TO = (
    "📖 How to use\n\n"
    "1. Signals arrive automatically during the New York kill zone (07:00–10:00 New York time).\n"
    "2. Place a LIMIT order at the Entry with the SL and TP from the signal (M5 chart).\n"
    "3. Cancel the order if it is not filled before 'Valid until'.\n"
    "4. At +1R: close HALF the position and move SL to entry (break-even).\n"
    "5. Risk max 0.5–1% of your account per trade.\n\n"
    "Buttons:\n"
    "🔎 Signal Now — checks the market immediately: sends the setup if one is valid, otherwise the status\n"
    "📈 Market Status — price, trend bias, liquidity levels, next session and news\n"
    "📜 Last Signals — the most recent signals\n"
    "📊 Performance — backtest results"
)
PRIVACY = (
    "🔒 Privacy\n\n"
    "This bot only uses your Telegram chat ID to send you messages. "
    "It does not collect, sell or share any other data. "
    "Signals are logged on the bot owner's computer only."
)
PRIVATE = "🔒 This is a private signal bot."

BUTTONS = [
    ["🔎 Signal Now", "📈 Market Status"],
    ["📜 Last Signals", "📊 Performance"],
    ["📖 How to use", "ℹ️ About"],
    ["🔒 Privacy"],
]
COMMANDS = [
    ("signal", "Check for a signal right now"),
    ("status", "Market status: price, bias, liquidity, session"),
    ("last", "Last signals"),
    ("stats", "Backtest performance"),
    ("help", "How to use the signals"),
    ("about", "About this bot"),
    ("privacy", "Privacy"),
]
# button text / command -> action name used by run_live.py
ACTIONS = {
    "🔎 Signal Now": "signal", "/signal": "signal",
    "📈 Market Status": "status", "/status": "status",
    "📜 Last Signals": "last", "/last": "last",
    "📊 Performance": "stats", "/stats": "stats",
    "📖 How to use": "help", "/help": "help",
    "ℹ️ About": "about", "/about": "about",
    "🔒 Privacy": "privacy", "/privacy": "privacy",
    "/start": "start",
}


def format_signal(s, symbol, tz="UTC"):
    arrow = "🟢 BUY" if s["direction"] == "BUY" else "🔴 SELL"
    one_r = s["entry"] + (s["tp"] - s["entry"]) / s["rr"]
    expiry = pd.Timestamp(s["expiry_time"]).tz_convert(tz)
    return (
        f"{arrow} {symbol} (limit)\n"
        f"Entry: {s['entry']:.2f}\n"
        f"SL: {s['sl']:.2f}\n"
        f"TP: {s['tp']:.2f}  (R:R {s['rr']})\n"
        f"Setup: {s.get('liquidity', 'asian')} sweep → CHoCH → {s['entry_model'].upper()} ({s['session']} KZ)\n"
        f"Valid until: {expiry:%H:%M} (cancel if not filled)\n"
        f"Manage: close half at +1R ({one_r:.2f}) and move SL to entry"
    )


class Notifier:
    """Sends alerts and handles button presses via Telegram long polling."""

    def __init__(self, cfg):
        live = cfg["live"]
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN") or live.get("telegram_bot_token")
        owner = os.environ.get("TELEGRAM_CHAT_ID") or live.get("telegram_chat_id")
        self.chats = [str(c) for c in [owner, *live.get("allowed_chat_ids", [])] if c]
        self.offset = None

    @property
    def enabled(self):
        return bool(self.token and self.chats)

    def _api(self, method, http_timeout=15, **params):
        data = urllib.parse.urlencode(
            {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in params.items()}
        ).encode()
        try:
            url = f"https://api.telegram.org/bot{self.token}/{method}"
            with urllib.request.urlopen(url, data=data, timeout=http_timeout) as r:
                return json.load(r).get("result")
        except urllib.error.HTTPError as e:
            try:
                reason = json.loads(e.read()).get("description", e)
            except ValueError:
                reason = e
            print(f"Telegram {method} error: {reason}")
        except Exception as e:  # never let Telegram errors stop the bot
            print(f"Telegram {method} error: {e}")
        return None

    def setup(self):
        """Set the bot's description, about text and command menu; skip messages sent while offline."""
        if not self.enabled:
            return
        self._api("setMyDescription", description=ABOUT[:512])
        self._api("setMyShortDescription", short_description=SHORT_ABOUT[:120])
        self._api("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])
        pending = self._api("getUpdates", offset=-1, timeout=0)
        if pending:
            self.offset = pending[-1]["update_id"] + 1

    def send(self, text, chat_id=None):
        """Send to one chat, or to every allowed chat. Always shows the button menu."""
        print("\n" + text + "\n", flush=True)
        if not self.enabled:
            return
        markup = {"keyboard": BUTTONS, "resize_keyboard": True, "is_persistent": True}
        for chat in [chat_id] if chat_id else self.chats:
            self._api("sendMessage", chat_id=chat, text=text, reply_markup=markup)

    def poll(self, timeout):
        """Wait up to `timeout` seconds for messages. Returns [(chat_id, action or None)]."""
        if not self.enabled:
            return []
        params = {"timeout": timeout, "allowed_updates": ["message"]}
        if self.offset is not None:
            params["offset"] = self.offset
        updates = self._api("getUpdates", http_timeout=timeout + 10, **params) or []
        out = []
        for u in updates:
            self.offset = u["update_id"] + 1
            msg = u.get("message") or {}
            chat = str(msg.get("chat", {}).get("id", ""))
            text = (msg.get("text") or "").split("@")[0].strip()
            if not chat:
                continue
            if chat not in self.chats:
                self._api("sendMessage", chat_id=chat, text=PRIVATE)
                continue
            out.append((chat, ACTIONS.get(text)))
        return out
