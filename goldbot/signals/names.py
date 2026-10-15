"""Friendly strategy names and the trading modes the user can pick in Telegram."""
import json

from goldbot.config import state_path

SETTINGS = state_path("settings.json")

# internal model key -> short, easy name
NAMES = {
    "v1": "Smart Reversal",
    "v2a": "NY Breakout",
    "v2b": "Trend Bounce",
    "v3": "Dip Buy",
}
DESCRIPTIONS = {
    "v1": "liquidity sweep → change of character → order block, New York session",
    "v2a": "New York opening range breakout and retest, busy market only",
    "v2b": "Bollinger re-entry in a strong trend (market order)",
    "v3": "buy the daily reopen after a down day (needs a low spread)",
}

MODES = {
    "safe": {
        "label": "🛡 Safe",
        "models": ["v1", "v2a", "v2b"],
        "summary": "3 strategies · ~1.5/week · 53% win · best for real money",
    },
    "more": {
        "label": "⚡ More Trades",
        "models": ["v1", "v2a", "v2b", "v3"],
        "summary": "4 strategies · ~3/week · 57% win · needs low spread",
    },
    "best": {
        "label": "🥇 Best Only",
        "models": ["v2a", "v2b"],
        "summary": "2 strategies · ~1.1/week · 53% win · highest PF",
    },
}
MODE_BUTTONS = {f"{m['label']} mode": key for key, m in MODES.items()}


def name(model):
    return NAMES.get(model, str(model))


def tag(model):
    return f"[{name(model)}]"


def _settings():
    try:
        return json.loads(SETTINGS.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _save(**kw):
    s = _settings()
    s.update(kw)
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s))


def get_mode(cfg):
    mode = _settings().get("mode") or cfg["live"].get("mode", "safe")
    return mode if mode in MODES else "safe"


def set_mode(mode):
    _save(mode=mode)


def get_auto():
    """Auto-trading switch (Telegram 🤖 Auto-Trade). Off unless the user turned it on."""
    return bool(_settings().get("auto", False))


def set_auto(on):
    _save(auto=bool(on))


def mode_text(current):
    lines = ["⚙️ Choose a mode:"]
    for key, m in MODES.items():
        mark = "✅" if key == current else "▫️"
        lines.append(f"{mark} {m['label']}: {m['summary']}")
    return "\n".join(lines)
