import pandas as pd

from goldbot.config import resolve

AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def resample(df, rule):
    """Resample OHLCV. Bars are labelled by their OPEN time (left edge)."""
    return df.resample(rule, label="left", closed="left").agg(AGG).dropna(subset=["open"])


def m5_path(cfg, symbol=None):
    return resolve(cfg["data"]["dir"]) / f"{cfg['data']['source']}_{symbol or cfg['symbol']}_M5.csv"


def save_m5(df, cfg):
    path = m5_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, date_format="%Y-%m-%d %H:%M:%S")
    return path


def load_m5(cfg, symbol=None):
    path = m5_path(cfg, symbol)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run: python run_download.py")
    df = pd.read_csv(path, index_col="time")
    df.index = pd.to_datetime(df.index).tz_localize("UTC")
    return df


def load_smt(cfg):
    """Correlated instrument for SMT divergence (silver), or None if not configured / not downloaded."""
    sym = cfg["strategy"].get("smt_symbol")
    if not sym:
        return None
    try:
        return load_m5(cfg, sym)
    except FileNotFoundError:
        print(f"  (SMT off: no {sym} data. Run: python run_download.py --source mt5 --symbol {sym})")
        return None
