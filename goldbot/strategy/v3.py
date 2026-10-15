"""V3-TEST (demo only): buy gold after the 18:00 New York daily reopen, Tuesday-Friday,
ONLY when the previous session closed down ("buy the dip" overnight).

Live-realistic rule (the bot only sees closed candles): signal when the 18:00-18:05 NY candle closes,
market BUY at 18:05, stop 3 x ATR(14) measured before the reopen, take-profit 1R, else close after 6h.
Backtest 2023-01..2026-10 at $0.30 spread: 342 trades, 60% win, PF 1.34, every year PF 1.28-1.40.
Spread-sensitive: PF 1.11 at $0.60, loses at $1.00. research/v3_improve.py documents the selection.
"""
import numpy as np
import pandas as pd

from goldbot.smc.indicators import atr
from goldbot.smc.sessions import session_frame

BAR = pd.Timedelta(minutes=5)
HOLD_HOURS = 6
STOP_ATR = 3.0
TP_R = 1.0
DAYS = (1, 2, 3, 4)  # session day Tue-Fri (Monday's reopen follows the weekend gap and lost money)


def generate_v3(m5, cfg):
    ny = m5.index.tz_convert("America/New_York")
    sess = session_frame(m5.index, cfg)
    a = atr(m5, 14).to_numpy()
    c = m5["close"].to_numpy()
    o = m5["open"].to_numpy()
    day = sess["session_day"].to_numpy()
    out = []
    for i in np.flatnonzero((ny.hour == 18) & (ny.minute == 0)):
        if i < 1 or np.isnan(a[i - 1]) or sess["session_day"].iat[i].weekday() not in DAYS:
            continue
        prev = np.flatnonzero(day[:i] == day[i - 1])  # bars of the previous session
        if not len(prev) or c[i - 1] >= o[prev[0]]:
            continue  # previous session did not close down
        entry = round(float(c[i]), 2)
        risk = STOP_ATR * a[i - 1]
        t = m5.index[i] + BAR
        out.append({
            "signal_time": t, "expiry_time": t + BAR, "direction": "BUY", "entry": entry,
            "sl": round(entry - risk, 2), "tp": round(entry + TP_R * risk, 2), "rr": TP_R, "order": "market",
            "model": "v3", "model_name": "V3-TEST reopen buy after a down day (demo only)",
            "management": f"TP {TP_R:g}R, else close after {HOLD_HOURS}h", "hold_hours": HOLD_HOURS,
            "session": "reopen", "liquidity": "reopen", "entry_model": "v3",
        })
    return pd.DataFrame(out)
