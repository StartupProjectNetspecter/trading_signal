"""One MetaTrader 5 handle for every platform.

Windows: the official MetaTrader5 package talks to the terminal directly.
Linux:   MT5 runs under Wine; the `mt5linux` bridge (an RPyC server started with
         `python -m mt5linux <wine python.exe>`) exposes the same API on a local port.
         Host/port come from MT5_BRIDGE_HOST / MT5_BRIDGE_PORT (default localhost:18812).
The bridge is connected lazily, so the bot can start before the bridge and retry.
"""
import os
import sys


class _Bridge:
    def __init__(self):
        self._mt5 = None

    def _get(self):
        if self._mt5 is None:
            from mt5linux import MetaTrader5

            self._mt5 = MetaTrader5(host=os.environ.get("MT5_BRIDGE_HOST", "localhost"),
                                    port=int(os.environ.get("MT5_BRIDGE_PORT", "18812")))
        return self._mt5

    def __getattr__(self, name):
        try:
            return getattr(self._get(), name)
        except (ConnectionError, OSError, EOFError):
            self._mt5 = None  # bridge restarted: reconnect on the next call
            raise


if sys.platform == "win32":
    try:
        import MetaTrader5 as mt5
    except ImportError:  # backtests still work without MT5
        mt5 = None
else:
    try:
        import mt5linux  # noqa: F401

        mt5 = _Bridge()
    except ImportError:
        mt5 = None
