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
    "🥇 Gold (XAUUSD) signal bot using ICT / Smart Money Concepts.\n\n"
    "Strategies (backtest Jan 2023 – Oct 2026):\n"
    "• Smart Reversal - liquidity sweep → CHoCH → order block · 51% win · PF 1.28\n"
    "• NY Breakout - New York opening range retest · 51% win · PF 1.68\n"
    "• Trend Bounce - Bollinger re-entry in a strong trend · 55% win · PF 1.42\n"
    "• Dip Buy - daily reopen buy after a down day · 60% win · PF 1.34 (needs low spread)\n\n"
    "Pick a mode with ⚙️ Mode: 🛡 Safe, ⚡ More Trades or 🥇 Best Only.\n"
    "Signals only — it never places trades. Past results do not guarantee future results. Not financial advice."
)
SHORT_ABOUT = "XAUUSD ICT/SMC signals: liquidity sweep → CHoCH → order block, New York session. Signals only, not financial advice."
HOW_TO = (
    "📖 How to use\n\n"
    "1. Signals arrive automatically, about 2–3 per week, mostly 18:00–02:00 Cambodia time.\n"
    "2. Each signal shows its strategy [Smart Reversal] [NY Breakout] [Trend Bounce] [Dip Buy] and the ORDER TYPE:\n"
    "   • LIMIT: place a limit order at the Entry. Cancel it if not filled before 'Valid until'.\n"
    "   • MARKET: enter now (within 5 minutes) at the current price.\n"
    "3. Always use the SL and TP from the signal.\n"
    "4. Follow the 'Manage' line (break-even / close half at +1R) and the max hold time.\n"
    "5. Risk max 0.5–1% of your account per trade.\n\n"
    "Buttons:\n"
    "🔎 Signal Now — checks the market immediately: sends the setup if one is valid, otherwise the status\n"
    "📈 Market Status — price, trend bias, liquidity levels, next session and news\n"
    "📜 Last Signals — the most recent signals\n"
    "📊 Performance — backtest results\n"
    "📒 My Results — live results of every signal, tracked automatically\n"
    "🗓 Daily Plan — today's windows, news and key levels (also sent every evening)\n\n"
    "⚙️ Mode lets you choose which strategies send signals (🛡 Safe is best for real money). "
    "ℹ️ ALERT messages are information (sweeps, trend changes, ranges), never trades.\n\n"
    "Each signal includes the lot size for your account balance and risk %. "
    "You get a result message when a trade closes, and a ⚠️ safety alert if live results drift far from the backtest."
)
PRIVACY = (
    "🔒 Privacy\n\n"
    "This bot only uses your Telegram chat ID to send you messages. "
    "It does not collect, sell or share any other data. "
    "Signals are logged on the bot owner's computer only."
)
PRIVATE = "🔒 This is a private signal bot."
OFFLINE = object()  # marker: Telegram could not be reached

BUTTONS = [
    ["🔎 Signal Now", "📈 Market Status"],
    ["📜 Last Signals", "📊 Performance"],
    ["📒 My Results", "🗓 Daily Plan"],
    ["⚙️ Mode"],
]  # How to use / About / Privacy stay available in the Menu as /help, /about, /privacy
COMMANDS = [
    ("signal", "Check for a signal right now"),
    ("status", "Market status: price, bias, liquidity, session"),
    ("last", "Last signals"),
    ("stats", "Backtest performance"),
    ("results", "My live results"),
    ("plan", "Today's market plan"),
    ("mode", "Choose trading mode"),
    ("help", "How to use the signals"),
    ("about", "About this bot"),
    ("privacy", "Privacy"),
]
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
