"""Add the current backtest results (win rate, profit factor, ...) to a git commit message.

Called by .githooks/prepare-commit-msg:
    python tools/commit_stats.py <commit-message-file>
Re-runs the backtest first if the strategy code or config changed since the last report.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TRADES = ROOT / "reports" / "trades.csv"
MARKER = "Backtest XAUUSD"
TRAILERS = ("Co-Authored-By:", "Signed-off-by:")


def report_is_stale():
    if not TRADES.exists():
        return True
    sources = [ROOT / "config.yaml", ROOT / "data" / "news_events.csv", *ROOT.glob("goldbot/**/*.py")]
    newest = max(p.stat().st_mtime for p in sources if p.exists())
    return newest > TRADES.stat().st_mtime


def stats_block():
    if report_is_stale():
        print("commit-stats: strategy or config changed, re-running backtest...", file=sys.stderr)
        r = subprocess.run([sys.executable, str(ROOT / "run_backtest.py")], cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0 or not TRADES.exists():
            return None
    import pandas as pd

    from goldbot.backtest.report import stats
    from goldbot.config import load_config

    bt = load_config()["backtest"]
    t = pd.read_csv(TRADES, parse_dates=["signal_time", "exit_time"])
    s = stats(t, bt["risk_per_trade"], bt["initial_equity"])
    if not s.get("trades"):
        return None
    start, end = t["signal_time"].min(), t["signal_time"].max()
    filled = t[t["filled"]]
    years = filled.groupby(filled["signal_time"].dt.year)["r"].sum()
    return (
        f"{MARKER} M5 ({start:%Y-%m-%d} -> {end:%Y-%m-%d}):\n"
        f"- Win rate {s['win_rate_%']}% | Profit factor {s['profit_factor']} | "
        f"Trades {s['trades']} of {len(t)} signals\n"
        f"- Total {s['total_R']:+}R ({s['return_%']:+}% at {bt['risk_per_trade']:.0%} risk) | "
        f"Max drawdown {s['max_drawdown_%']}% | Longest losing streak {s['max_losing_streak']}\n"
        f"- By year: " + ", ".join(f"{y} {v:+.1f}R" for y, v in years.items())
    )


def main(msg_file):
    path = Path(msg_file)
    msg = path.read_text(encoding="utf-8")
    if MARKER in msg:
        return  # already has stats (e.g. amend)
    block = stats_block()
    if not block:
        return
    lines = msg.rstrip("\n").split("\n")
    # keep git trailers (Co-Authored-By...) at the very end so git still recognises them
    cut = len(lines)
    while cut > 0 and (lines[cut - 1].startswith(TRAILERS) or (lines[cut - 1] == "" and cut < len(lines))):
        cut -= 1
    body, trailers = lines[:cut], [line for line in lines[cut:] if line]
    out = "\n".join(body).rstrip("\n") + "\n\n" + block + "\n"
    if trailers:
        out += "\n" + "\n".join(trailers) + "\n"
    path.write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
