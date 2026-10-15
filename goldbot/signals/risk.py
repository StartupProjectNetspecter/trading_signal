"""Position size for a signal: lots so that hitting the stop loses `risk_pct` of the balance."""
import math


def lot_size(entry, sl, balance, risk_pct, specs):
    """Returns (lots, money_at_risk, note). specs from mt5_source.symbol_specs()."""
    dist = abs(entry - sl)
    if not specs or dist <= 0 or balance <= 0:
        return None, None, "lot size unavailable"
    risk_money = balance * risk_pct
    raw = risk_money / (dist * specs["value_per_price_per_lot"])
    step = specs["volume_step"] or 0.01
    lots = math.floor(raw / step + 1e-9) * step
    lots = min(round(lots, 2), specs["volume_max"])
    if lots < specs["volume_min"]:
        min_risk = specs["volume_min"] * dist * specs["value_per_price_per_lot"]
        return specs["volume_min"], min_risk, f"min lot = {min_risk / balance:.1%} risk - skip?"
    actual = lots * dist * specs["value_per_price_per_lot"]
    return lots, actual, ""


def lot_line(entry, sl, account, risk_pct, specs):
    if not account:
        return "Lot: (account not available)"
    balance, ccy = account
    lots, money, note = lot_size(entry, sl, balance, risk_pct, specs)
    if lots is None:
        return f"Lot: {note}"
    line = f"Lot {lots:.2f} · risk {money:,.0f} {ccy} ({money / balance:.1%})"
    return line + (f"\n⚠️ {note}" if note else "")
