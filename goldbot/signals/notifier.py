"""Telegram: signal alerts, bot profile (description + commands) and the button menu."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

from goldbot.signals.names import MODE_BUTTONS, name

ABOUT = (
    "🥇 Gold (XAUUSD) signal bot · ICT/SMC\n"
    "Smart Reversal · NY Breakout · Trend Bounce · Dip Buy\n"
    "Backtest 2023–2026: ~55% win · PF ~1.4\n"
    "Not financial advice."
)
SHORT_ABOUT = "Gold (XAUUSD) ICT/SMC signals with entry, SL and TP. Not financial advice."
HOW_TO = (
    "📖 How to use\n"
    "• limit = place order at Entry (cancel at 'until')\n"
    "• NOW = enter at market\n"
    "• TP1 = do the action shown · TP2 = final target\n"
    "• ⏱ = close if still open\n"
    "• ℹ️ messages are info, not trades\n"
    "• Risk max 1% per trade"
)
PRIVACY = "🔒 Only your chat ID is used. No data is shared."
PRIVATE = "🔒 This is a private signal bot."
OFFLINE = object()  # marker: Telegram could not be reached

BUTTONS = [
    ["🔎 Signal Now", "📈 Market Status"],
    ["📜 Last Signals", "📊 Performance"],
    ["📒 My Results", "🗓 Daily Plan"],
    ["⚙️ Mode", "🤖 Auto-Trade"],
]  # How to use / About / Privacy stay available in the Menu as /help, /about, /privacy
COMMANDS = [
    ("signal", "Check for a signal right now"),
    ("status", "Market status: price, bias, liquidity, session"),
    ("last", "Last signals"),
    ("stats", "Backtest performance"),
    ("results", "My live results"),
    ("plan", "Today's market plan"),
    ("mode", "Choose trading mode"),
    ("auto", "Auto-trading on demo (on/off)"),
    ("help", "How to use the signals"),
    ("about", "About this bot"),
    ("privacy", "Privacy"),
]
AUTO_KEYBOARD = [["✅ Auto ON", "⛔ Auto OFF"], ["⬅️ Back"]]
MODE_KEYBOARD = [list(MODE_BUTTONS)[:2], list(MODE_BUTTONS)[2:] + ["⬅️ Back"]]
# button text / command -> action name used by run_live.py
ACTIONS = {
    "🔎 Signal Now": "signal", "/signal": "signal",
    "📈 Market Status": "status", "/status": "status",
    "📜 Last Signals": "last", "/last": "last",
    "📊 Performance": "stats", "/stats": "stats",
    "📒 My Results": "results", "/results": "results",
    "🗓 Daily Plan": "plan", "/plan": "plan",
    "⚙️ Mode": "mode", "/mode": "mode", "⬅️ Back": "menu",
    "🤖 Auto-Trade": "auto", "/auto": "auto", "✅ Auto ON": "auto_on", "⛔ Auto OFF": "auto_off",
    **{label: f"set_mode:{key}" for label, key in MODE_BUTTONS.items()},
    "📖 How to use": "help", "/help": "help",
    "ℹ️ About": "about", "/about": "about",
    "🔒 Privacy": "privacy", "/privacy": "privacy",
    "/start": "start",
}


# per strategy: what to do at TP1 (+1R) and the maximum hold time (matches each backtest)
PLAN = {
    "v1": ("close half, move SL to entry", 8),
    "v2a": ("move SL to entry", 8),
    "v2b": ("close half, move SL to entry", 4),
    "v3": (None, 6),
}


def format_signal(s, symbol, tz="UTC"):
    """Short signal: direction, entry, SL, TP1/TP2 and max hold. Lot size is appended by the bot."""
    model = s.get("model", "v1")
    arrow = "🟢 BUY" if s["direction"] == "BUY" else "🔴 SELL"
    tp1_action, hold = PLAN.get(model, (None, s.get("hold_hours", 8)))
    expiry = pd.Timestamp(s["expiry_time"]).tz_convert(tz)
    if s.get("order") == "market":
        entry = f"Entry: NOW ~{s['entry']:.2f} (market)"
        close_by = f"⏱ Close by {(pd.Timestamp(s['signal_time']) + pd.Timedelta(hours=hold)).tz_convert(tz):%H:%M} if still open"
    else:
        entry = f"Entry: {s['entry']:.2f} (limit, until {expiry:%H:%M})"
        close_by = f"⏱ Close after {hold}h if still open"
    lines = [f"{arrow} {symbol} · {name(model)}", entry, f"SL: {s['sl']:.2f}"]
    if tp1_action and s["rr"] > 1:
        one_r = s["entry"] + (s["tp"] - s["entry"]) / s["rr"]
        lines += [f"TP1: {one_r:.2f} → {tp1_action}", f"TP2: {s['tp']:.2f}"]
    else:
        lines.append(f"TP: {s['tp']:.2f}")
    lines.append(close_by)
    return "\n".join(lines)


class Notifier:
    """Sends alerts and handles button presses via Telegram long polling."""

    def __init__(self, cfg):
        live = cfg["live"]
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN") or live.get("telegram_bot_token")
        owner = os.environ.get("TELEGRAM_CHAT_ID") or live.get("telegram_chat_id")
        self.chats = [str(c) for c in [owner, *live.get("allowed_chat_ids", [])] if c]
        self.offset = None
        self.outbox = []          # messages that could not be sent (no internet); retried automatically
        self.online = True
        self.needs_setup = False
        self._last_warn = 0.0

    @property
    def enabled(self):
        return bool(self.token and self.chats)

    def _offline(self, method, err):
        """Remember the outage; log once, then at most once a minute."""
        now = time.time()
        if self.online or now - self._last_warn > 60:
            queued = f", {len(self.outbox)} message(s) queued" if self.outbox else ""
            print(f"Telegram unreachable ({method}: {err}). Retrying{queued}...", flush=True)
            self._last_warn = now
        self.online = False

    def _api(self, method, http_timeout=15, **params):
        """Returns the result, None on a Telegram error, or OFFLINE when there is no connection."""
        data = urllib.parse.urlencode(
            {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in params.items()}
        ).encode()
        try:
            url = f"https://api.telegram.org/bot{self.token}/{method}"
            with urllib.request.urlopen(url, data=data, timeout=http_timeout) as r:
                result = json.load(r).get("result")
            if not self.online:
                print("Telegram connection restored.", flush=True)
                self.online = True
            return result
        except urllib.error.HTTPError as e:  # Telegram answered: a real error, do not retry
            try:
                reason = json.loads(e.read()).get("description", e)
            except ValueError:
                reason = e
            print(f"Telegram {method} error: {reason}")
            return None
        except Exception as e:  # no internet / DNS / timeout: never let it stop the bot
            self._offline(method, e)
            return OFFLINE

    def setup(self):
        """Set the bot's description, about text and command menu; skip messages sent while offline."""
        if not self.enabled:
            return
        res = [
            self._api("setMyDescription", description=ABOUT[:512]),
            self._api("setMyShortDescription", short_description=SHORT_ABOUT[:120]),
            self._api("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS]),
        ]
        self.needs_setup = OFFLINE in res
        pending = self._api("getUpdates", offset=-1, timeout=0)
        if pending and pending is not OFFLINE:
            self.offset = pending[-1]["update_id"] + 1

    def send(self, text, chat_id=None, buttons=None):
        """Send to one chat, or to every allowed chat. Queued and retried if there is no connection.
        `buttons`: keyboard to show with this message (default: the main menu)."""
        print("\n" + text + "\n", flush=True)
        if not self.enabled:
            return
        for chat in [chat_id] if chat_id else self.chats:
            self._deliver(chat, text, buttons)

    def _deliver(self, chat, text, buttons=None):
        markup = {"keyboard": buttons or BUTTONS, "resize_keyboard": True, "is_persistent": True}
        if self.outbox or self._api("sendMessage", chat_id=chat, text=text, reply_markup=markup) is OFFLINE:
            self.outbox.append((chat, text, time.time()))  # keep order: never send newer messages first

    def flush(self):
        """Send queued messages (oldest first) once the connection is back."""
        while self.outbox:
            chat, text, queued_at = self.outbox[0]
            late = time.time() - queued_at
            note = f"\n\n⏱ Delayed {int(late // 60)} min by a connection problem - check prices before acting." if late > 120 else ""
            markup = {"keyboard": BUTTONS, "resize_keyboard": True, "is_persistent": True}
            if self._api("sendMessage", chat_id=chat, text=text + note, reply_markup=markup) is OFFLINE:
                return
            self.outbox.pop(0)

    def poll(self, timeout):
        """Wait up to `timeout` seconds for messages. Returns [(chat_id, action or None)]."""
        if not self.enabled:
            return []
        if self.outbox:
            self.flush()
        if self.needs_setup and self.online:
            self.setup()
        params = {"timeout": timeout, "allowed_updates": ["message"]}
        if self.offset is not None:
            params["offset"] = self.offset
        updates = self._api("getUpdates", http_timeout=timeout + 10, **params)
        if updates is OFFLINE:
            time.sleep(min(timeout, 20))  # no connection: wait instead of spinning
            return []
        out = []
        for u in updates or []:
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
