"""Download history and save it as M5 candles (UTC).

    python run_download.py                     # source from config.yaml
    python run_download.py --source mt5        # from your MT5 terminal
    python run_download.py --start 2023-01-01
"""
import argparse
from datetime import date

from goldbot.config import load_config, resolve
from goldbot.data import dukascopy, store


def main():
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=None)
    cfg_path = pre.parse_known_args()[0].config
    cfg = load_config(cfg_path)
    ap = argparse.ArgumentParser(parents=[pre])
    ap.add_argument("--source", choices=["dukascopy", "mt5"], default=cfg["data"]["source"])
    ap.add_argument("--start", default=cfg["data"]["start"])
    ap.add_argument("--end", default=cfg["data"]["end"])
    ap.add_argument("--symbol", default=None, help="MT5 symbol override, e.g. XAGUSD")
    args = ap.parse_args()
    cfg["data"]["source"] = args.source
    if args.symbol:
        cfg["symbol"] = cfg["data"]["mt5_symbol"] = args.symbol

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else dukascopy.default_end()
    print(f"Downloading {cfg['symbol']} {start} -> {end} from {args.source}")

    if args.source == "dukascopy":
        cache = resolve(cfg["data"]["dir"]) / "raw" / "dukascopy" / cfg["data"]["dukascopy_instrument"]
        m1 = dukascopy.download_m1(
            cfg["data"]["dukascopy_instrument"], start, end, cache, cfg["data"]["dukascopy_divisor"]
        )
        m5 = store.resample(m1, "5min")
    else:
        from goldbot.data import mt5_source

        sym = cfg["data"]["mt5_symbol"]
        mt5_source.connect(sym)
        try:
            m5, tz = mt5_source.download(sym, "M5", start, end, cfg["data"]["mt5_server_tz"])
            print(f"  MT5 server timezone: {tz}")
        finally:
            mt5_source.shutdown()

    path = store.save_m5(m5, cfg)
    print(f"Saved {len(m5):,} M5 bars ({m5.index[0]} -> {m5.index[-1]}) to {path}")


if __name__ == "__main__":
    main()
