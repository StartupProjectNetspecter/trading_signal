"""More classic human-trader concepts.  python -m research.new_concepts2

1. Round numbers ($50 / $100 levels): bounce (fade first touch) or breakout (close through).
2. Previous day high/low: fade the first touch, or trade the close-through breakout.
3. Asian range breakout during London / New York.
Same costs and protocol as research/new_concepts.py (spread $0.60, choose 2023-24, confirm 2025, report 2026).
"""
import itertools

import numpy as np
import pandas as pd

from goldbot.config import load_config
from goldbot.data.store import load_m5
from goldbot.smc.indicators import atr
from goldbot.smc.sessions import session_frame
from goldbot.strategy.asian_sweep import BAR, _Levels
from research.new_concepts import report, run_sim


def _sig(t, d, entry, sl, rr, order="market", expiry_bars=1):
    risk = (entry - sl) * d
    return {"signal_time": t + BAR, "expiry_time": t + expiry_bars * BAR, "direction": "BUY" if d == 1 else "SELL",
            "entry": entry, "sl": sl, "tp": entry + d * rr * risk, "rr": rr, "order": order}


def _base(m5, cfg):
    sess = session_frame(m5.index, cfg)
    return (sess, m5["open"].to_numpy(), m5["high"].to_numpy(), m5["low"].to_numpy(), m5["close"].to_numpy(),
            atr(m5, 14).to_numpy(), sess["ny_hour"].to_numpy(), sess["news_block"].to_numpy(), sess["session_day"].to_numpy())


def round_numbers(m5, cfg):
    sess, o, h, l, c, a, hr, news, day = _base(m5, cfg)
    out = []
    for step, mode, rr, hours in itertools.product([50, 100], ["bounce", "breakout"], [1.0, 1.5, 2.0], [(2, 11), (7, 15)]):
        sigs, used = [], set()
        for i in range(1, len(m5)):
            if not (hours[0] <= hr[i] < hours[1]) or news[i] or np.isnan(a[i]):
                continue
            lvl_up = np.ceil(l[i] / step) * step  # a round level inside this bar's range
            if not (l[i] <= lvl_up <= h[i]) or (day[i], lvl_up) in used:
                continue
            came_from_above = c[i - 1] > lvl_up
            if mode == "bounce":
                d = 1 if came_from_above else -1  # support from above, resistance from below
                if (c[i] - lvl_up) * d <= 0:
                    continue  # needs a rejection close back on the original side
                sl = lvl_up - d * 1.0 * a[i]
            else:
                d = -1 if came_from_above else 1  # close through the level
                if (c[i] - lvl_up) * d <= 0.2 * a[i]:
                    continue
                sl = lvl_up - d * 0.5 * a[i]
            used.add((day[i], lvl_up))
            if (c[i] - sl) * d < 1.0:
                continue
            sigs.append(_sig(m5.index[i], d, c[i], sl, rr))
        out.append((f"Round ${step} {mode} RR{rr} NY {hours[0]:02d}-{hours[1]:02d}h", pd.DataFrame(sigs)))
    return out


def prev_day_levels(m5, cfg):
    sess, o, h, l, c, a, hr, news, day = _base(m5, cfg)
    lv = _Levels(m5, sess)
    pdh = lv.prev_day["high"].reindex(day).to_numpy()
    pdl = lv.prev_day["low"].reindex(day).to_numpy()
    out = []
    for mode, rr, hours in itertools.product(["fade", "breakout"], [1.0, 1.5, 2.0], [(2, 11), (7, 15)]):
        sigs, done = [], set()
        for i in range(1, len(m5)):
            if not (hours[0] <= hr[i] < hours[1]) or news[i] or np.isnan(a[i]) or np.isnan(pdh[i]):
                continue
            for lvl, side in ((pdh[i], 1), (pdl[i], -1)):  # side +1 = level above (high)
                if (day[i], side) in done:
                    continue
                touched = h[i] >= lvl if side == 1 else l[i] <= lvl
                if not touched:
                    continue
                done.add((day[i], side))
                if mode == "fade":
                    d = -side
                    if (c[i] - lvl) * side >= 0:
                        continue  # must close back inside the previous range
                    sl = (h[i] if side == 1 else l[i]) + side * 0.3 * a[i]
                else:
                    d = side
                    if (c[i] - lvl) * side <= 0.2 * a[i]:
                        continue
                    sl = lvl - side * 0.7 * a[i]
                if (c[i] - sl) * d < 1.0:
                    continue
                sigs.append(_sig(m5.index[i], d, c[i], sl, rr))
        out.append((f"PDH/PDL {mode} RR{rr} NY {hours[0]:02d}-{hours[1]:02d}h", pd.DataFrame(sigs)))
    return out


def asian_breakout(m5, cfg):
    sess, o, h, l, c, a, hr, news, day = _base(m5, cfg)
    lv = _Levels(m5, sess)
    ah = lv.asian["asian_high"].reindex(day).to_numpy()
    al = lv.asian["asian_low"].reindex(day).to_numpy()
    asian = sess["asian"].to_numpy()
    out = []
    for rr, hours, max_rng, sl_mode in itertools.product([1.0, 1.5, 2.0], [(2, 5), (2, 8), (7, 10)], [3.0, 6.0], ["mid", "far"]):
        sigs, done = [], set()
        for i in range(1, len(m5)):
            if asian[i] or not (hours[0] <= hr[i] < hours[1]) or news[i] or np.isnan(a[i]) or np.isnan(ah[i]) or day[i] in done:
                continue
            if ah[i] - al[i] > max_rng * a[i]:
                continue
            d = 1 if c[i] > ah[i] else -1 if c[i] < al[i] else 0
            if not d:
                continue
            done.add(day[i])
            sl = (ah[i] + al[i]) / 2 if sl_mode == "mid" else (al[i] if d == 1 else ah[i])
            if (c[i] - sl) * d < 1.0:
                continue
            sigs.append(_sig(m5.index[i], d, c[i], sl, rr))
        out.append((f"Asian breakout RR{rr} NY {hours[0]:02d}-{hours[1]:02d}h range<{max_rng}ATR SL {sl_mode}", pd.DataFrame(sigs)))
    return out


def main():
    cfg = load_config()
    m5 = load_m5(cfg)
    pd.set_option("display.width", 230)
    report("4. Round numbers ($50/$100)", run_sim(round_numbers(m5, cfg), m5, cfg))
    report("5. Previous day high/low", run_sim(prev_day_levels(m5, cfg), m5, cfg))
    report("6. Asian range breakout", run_sim(asian_breakout(m5, cfg), m5, cfg))


if __name__ == "__main__":
    main()
