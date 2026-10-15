"""Friendly strategy names and the trading modes the user can pick in Telegram."""
import json

from goldbot.config import resolve

SETTINGS = resolve("data/settings.json")

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
        "summary": "Smart Reversal + NY Breakout + Trend Bounce. ~1.5 trades/week · 53% win · PF 1.48. Best for real money.",
    },
    "more": {
        "label": "⚡ More Trades",
        "models": ["v1", "v2a", "v2b", "v3"],
        "summary": "Safe + Dip Buy. ~3 trades/week · 57% win · PF 1.40. Dip Buy needs a low spread - demo first.",
    },
    "best": {
        "label": "🥇 Best Only",
        "models": ["v2a", "v2b"],
        "summary": "NY Breakout + Trend Bounce only. ~1.1 trades/week · 53% win · PF 1.57 (highest).",
    },
}
MODE_BUTTONS = {f"{m['label']} mode": key for key, m in MODES.items()}


def name(model):
    return NAMES.get(model, str(model))


def tag(model):
    return f"[{name(model)}]"


def get_mode(cfg):
    try:
        mode = json.loads(SETTINGS.read_text()).get("mode")
    except (FileNotFoundError, ValueError):
        mode = None
    mode = mode or cfg["live"].get("mode", "safe")
    return mode if mode in MODES else "safe"


def set_mode(mode):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps({"mode": mode}))


def mode_text(current):
    lines = ["⚙️ Trading mode - tap a button below to change:\n"]
    for key, m in MODES.items():
        mark = "✅ " if key == current else "▫️ "
        lines.append(f"{mark}{m['label']}\n   {m['summary']}")
    return "\n".join(lines)
