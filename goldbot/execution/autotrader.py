"""Auto-trading: places and manages the bot's signals in MT5 exactly like the backtest rules.

Safety first:
  * refuses to trade unless the account is DEMO (set auto_trade.allow_real: true to override - not advised)
  * off until switched on in Telegram (🤖 Auto-Trade), per-trade risk from live.risk_per_trade
  * max open positions, skips trades whose minimum lot risks too much, pauses for the day after a loss limit
  * cancels pending orders at their expiry time and when a news block starts

Per signal: limit / market order with SL and final TP -> at TP1 (+1R) close half and/or move SL to entry
(as the strategy's backtest) -> close at the max hold time.
"""
import json
import math
import time

import pandas as pd

from goldbot.config import resolve
from goldbot.signals.names import name
from goldbot.signals.notifier import PLAN
from goldbot.signals.risk import lot_size
from goldbot.smc.sessions import news_mask

from goldbot.data.mt5_api import mt5  # Windows: MetaTrader5 package · Linux: mt5linux bridge

STATE = resolve("data/auto_state.json")
MAGIC = {"v1": 260101, "v2a": 260102, "v2b": 260103, "v3": 260104}
OK = (10009, 10008)  # TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED


class AutoTrader:
    def __init__(self, cfg, symbol, notify):
        self.cfg = cfg
        self.sym = symbol
        self.notify = notify
        self.opts = cfg.get("auto_trade", {})
        self.state = self._load()

    # ---- persistence -------------------------------------------------------
    def _load(self):
        try:
            return json.loads(STATE.read_text())
        except (FileNotFoundError, ValueError):
            return {}

    def _save(self):
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(self.state, indent=1, default=str))

    # ---- checks ------------------------------------------------------------
    def ready(self):
        """(ok, reason). Auto-trading only runs on a demo account with Algo Trading enabled."""
        if mt5 is None:
            return False, "MetaTrader5 package missing"
        acc, term = mt5.account_info(), mt5.terminal_info()
        if acc is None or term is None:
            return False, "MT5 not connected"
        if acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO and not self.opts.get("allow_real", False):
            return False, "account is NOT demo - auto-trading refused (demo only)"
        if not term.trade_allowed:
            return False, "'Algo Trading' is OFF in MT5 - click the Algo Trading button in the MT5 toolbar"
        if not acc.trade_allowed:
            return False, "trading is not allowed on this account"
        return True, "ok"

    def _today_r(self):
        today = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
        return sum(t.get("realized_r", 0.0) for t in self.state.values() if str(t.get("closed_at", "")).startswith(today))

    def _open_count(self):
        return sum(1 for t in self.state.values() if t["status"] in ("pending", "open"))

    # ---- helpers -----------------------------------------------------------
    def _filling(self):
        mode = mt5.symbol_info(self.sym).filling_mode
        return mt5.ORDER_FILLING_IOC if mode & 2 else mt5.ORDER_FILLING_FOK if mode & 1 else mt5.ORDER_FILLING_RETURN

    def _round(self, price):
        return round(price, mt5.symbol_info(self.sym).digits)

    def _send(self, req):
        res = mt5.order_send(req)
        if res is None:
            return None, f"order_send failed: {mt5.last_error()}"
        if res.retcode not in OK:
            return None, f"rejected ({res.retcode}): {res.comment}"
        return res, ""

    def _close(self, pos, volume, why):
        tick = mt5.symbol_info_tick(self.sym)
        buy = pos.type == mt5.POSITION_TYPE_BUY
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": self.sym, "position": pos.ticket, "volume": volume,
               "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY, "price": tick.bid if buy else tick.ask,
               "deviation": 50, "magic": pos.magic, "comment": why[:31], "type_filling": self._filling()}
        return self._send(req)

    # ---- placing -----------------------------------------------------------
    def place(self, key, s):
        """Place one signal. Returns a short status line for Telegram."""
        ok, why = self.ready()
        if not ok:
            return f"🤖 Skipped: {why}"
        if key in self.state:
            return ""
        if self._open_count() >= self.opts.get("max_open_trades", 3):
            return "🤖 Skipped: max open trades"
        loss_limit = self.opts.get("max_daily_loss_r", 3.0)
        if self._today_r() <= -loss_limit:
            return f"🤖 Paused today: -{loss_limit:g}R limit"
        model = s.get("model", "v1")
        d = 1 if s["direction"] == "BUY" else -1
        acc = mt5.account_info()
        from goldbot.data.mt5_source import symbol_specs  # local import keeps this module MT5-optional

        lots, risk_money, note = lot_size(s["entry"], s["sl"], acc.balance, self.cfg["live"].get("risk_per_trade", 0.01), symbol_specs(self.sym))
        if not lots or note:
            return f"🤖 Skipped: {note or 'no lot size'}"
        tick = mt5.symbol_info_tick(self.sym)
        sl, tp = self._round(s["sl"]), self._round(s["tp"])
        market_px = tick.ask if d == 1 else tick.bid
        if (market_px - sl) * d <= 0 or (tp - market_px) * d <= 0:
            return "🤖 Skipped: price past SL/TP"
        entry = self._round(s["entry"])
        use_market = s.get("order") == "market" or (market_px - entry) * d <= 0  # limit already reachable -> take it now
        base = {"symbol": self.sym, "volume": lots, "sl": sl, "tp": tp, "deviation": 50, "magic": MAGIC.get(model, 260100),
                "comment": f"{model} {pd.Timestamp(s['signal_time']):%m%d%H%M}"}
        if use_market:
            req = {**base, "action": mt5.TRADE_ACTION_DEAL, "type": mt5.ORDER_TYPE_BUY if d == 1 else mt5.ORDER_TYPE_SELL,
                   "price": market_px, "type_filling": self._filling()}
        else:
            req = {**base, "action": mt5.TRADE_ACTION_PENDING, "type": mt5.ORDER_TYPE_BUY_LIMIT if d == 1 else mt5.ORDER_TYPE_SELL_LIMIT,
                   "price": entry, "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_RETURN}
        res, err = self._send(req)
        if res is None:
            return f"🤖 Order failed: {err}"
        tp1_action, hold = PLAN.get(model, (None, 8))
        rr = float(s["rr"])
        self.state[key] = {
            "model": model, "d": d, "entry": entry, "sl": sl, "tp": tp, "lots": lots, "risk": abs(entry - sl),
            "tp1": self._round(entry + (tp - entry) / rr) if tp1_action and rr > 1 else None, "tp1_action": tp1_action,
            "tp1_done": False, "hold_hours": hold, "expiry": str(pd.Timestamp(s["expiry_time"])),
            "status": "open" if use_market else "pending", "order": int(res.order), "position": int(res.order) if use_market else None,
            "opened_at": str(pd.Timestamp.now(tz="UTC")) if use_market else None, "realized_r": 0.0,
        }
        self._save()
        kind = "MARKET" if use_market else "LIMIT"
        return f"🤖 {s['direction']} {kind} {lots:.2f} @ {res.price or entry:.2f} placed"

    # ---- managing ----------------------------------------------------------
    def manage(self):
        """Run every loop: fills, expiries, news cancels, TP1, time exits and closed-trade reports."""
        if not self.state or mt5 is None or mt5.account_info() is None:
            return
        now = pd.Timestamp.now(tz="UTC")
        news_now = bool(news_mask(pd.DatetimeIndex([now.floor("5min")]), self.cfg)[0])
        orders = {o.ticket: o for o in (mt5.orders_get(symbol=self.sym) or [])}
        positions = {p.ticket: p for p in (mt5.positions_get(symbol=self.sym) or [])}
        changed = False
        for key, t in self.state.items():
            if t["status"] == "pending":
                if t["order"] in orders:
                    if now >= pd.Timestamp(t["expiry"]) or news_now:
                        res, err = self._send({"action": mt5.TRADE_ACTION_REMOVE, "order": t["order"]})
                        why = "news block" if news_now else "not filled in time"
                        t["status"], changed = ("cancelled" if res else "pending"), True
                        if res:
                            self.notify(f"🤖 {name(t['model'])}: order cancelled ({why})")
                    continue
                pos = positions.get(t["order"]) or next((p for p in positions.values() if p.identifier == t["order"]), None)
                if pos is None:  # order vanished without a position (filled and closed instantly, or removed manually)
                    t["status"], changed = "closed", True
                    self._report_closed(key, t)
                    continue
                t.update(status="open", position=int(pos.ticket), opened_at=str(now))
                changed = True
                self.notify(f"🤖 {name(t['model'])}: filled @ {pos.price_open:.2f}")
            if t["status"] != "open":
                continue
            pos = positions.get(t["position"])
            if pos is None:
                t["status"], changed = "closed", True
                self._report_closed(key, t)
                continue
            tick = mt5.symbol_info_tick(self.sym)
            px = tick.bid if t["d"] == 1 else tick.ask
            if t["tp1"] and not t["tp1_done"] and (px - t["tp1"]) * t["d"] >= 0:
                msgs = []
                if "close half" in t["tp1_action"]:
                    info = mt5.symbol_info(self.sym)
                    half = math.floor(pos.volume / 2 / info.volume_step + 1e-9) * info.volume_step
                    if half >= info.volume_min:
                        res, err = self._close(pos, round(half, 2), "TP1 half")
                        msgs.append(f"closed {half:.2f} lot" if res else f"half close failed: {err}")
                    else:
                        msgs.append("lot too small to close half")
                res, err = self._send({"action": mt5.TRADE_ACTION_SLTP, "symbol": self.sym, "position": pos.ticket,
                                       "sl": self._round(pos.price_open), "tp": t["tp"]})
                msgs.append("SL moved to entry" if res else f"SL move failed: {err}")
                t["tp1_done"], changed = True, True
                self.notify(f"🤖 {name(t['model'])}: TP1 ✅ " + ", ".join(msgs))
            if t.get("opened_at") and now >= pd.Timestamp(t["opened_at"]) + pd.Timedelta(hours=t["hold_hours"]):
                res, err = self._close(pos, pos.volume, "max hold time")
                if res:
                    self.notify(f"🤖 {name(t['model'])}: closed (time)")
                changed = True
        if changed:
            self._save()

    def _report_closed(self, key, t):
        """Sum the realized profit of this trade's deals and report it in R."""
        time.sleep(0.5)
        frm = pd.Timestamp(t.get("opened_at") or pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=3)) - pd.Timedelta(days=1)
        to = pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)
        deals = mt5.history_deals_get(frm.tz_convert("UTC").tz_localize(None).to_pydatetime(), to.tz_localize(None).to_pydatetime()) or []
        pid = t.get("position") or t["order"]
        mine = [x for x in deals if x.position_id == pid]
        profit = sum(x.profit + x.commission + x.swap for x in mine)
        from goldbot.data.mt5_source import symbol_specs

        spec = symbol_specs(self.sym)
        risk_money = t["risk"] * t["lots"] * (spec["value_per_price_per_lot"] if spec else 100)
        r = profit / risk_money if risk_money else 0.0
        t.update(realized_r=r, closed_at=str(pd.Timestamp.now(tz="UTC")), profit=profit)
        icon = "✅" if profit > 0 else "➖" if abs(profit) < 1e-9 else "❌"
        self.notify(f"🤖 {icon} {name(t['model'])}: {profit:+,.2f} ({r:+.2f}R)")

    def status_text(self, on):
        ok, why = self.ready()
        open_ = [t for t in self.state.values() if t["status"] in ("pending", "open")]
        closed = [t for t in self.state.values() if t["status"] == "closed"]
        total = sum(t.get("profit", 0.0) for t in closed)
        lines = [f"🤖 Auto-Trade {'ON ✅' if on else 'OFF ⛔'}" + ("" if ok else f"\n⚠️ {why}"),
                 f"Open {len(open_)} · closed {len(closed)} · P/L {total:+,.2f}",
                 f"Risk {self.cfg['live'].get('risk_per_trade', 0.01):.0%} · max {self.opts.get('max_open_trades', 3)} open · demo only"]
        return "\n".join(lines)
