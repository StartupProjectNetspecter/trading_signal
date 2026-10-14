# Gold SMC/ICT Signal Bot (XAUUSD)

Rule-based signal bot for gold using ICT / Smart Money Concepts. No machine learning yet.
Every rule is plain math on candles, and nothing uses future bars (tested in `tests/test_smc.py`).

## Strategy: Liquidity Sweep → CHoCH → Order Block (New York session)

| Step | Rule |
|---|---|
| 1. Liquidity | Asian range high/low (20:00–00:00 NY) and London session high/low (02:00–05:00 NY). Optional: previous day high/low |
| 2. Sweep | Price trades through one of those levels (the level must still be intact when the session starts) |
| 3. CHoCH | Within 2 hours, an M5 candle **closes** beyond the last confirmed swing |
| 4. Filters | CHoCH is inside the New York kill zone (07:00–10:00 NY), agrees with the H1 structure bias, not near NFP/news. Optional: SMT divergence vs silver |
| 5. Entry | Limit order at 50% of the order block. Cancelled after 1 hour if not filled |
| 6. Risk | SL beyond the sweep extreme + 0.5 ATR. Close half at +1R and move SL to break-even, rest targets 2R |

All values can be changed in [config.yaml](config.yaml).

### Deep-test results (Jan 2023 → Oct 2026, 320 variants)
- Current config: **74 trades, 54% win rate, profit factor 1.44, +14.7R, max drawdown 7%**. Positive in all 4 years.
- Walk-forward (choose settings on past data only, trade the next year): PF 1.25 in 2025, 1.30 in 2026.
  That is the realistic expectation, and lower than the best backtest.
- What helped: London high/low sweeps in NY, NY-only, order block entries, break-even/partial.
- What did not: SMT filter (too few trades), FVG entries, 1R targets, H4/daily bias.

## Project layout

```
config.yaml            gold settings
run_download.py        1) download history  -> data/<source>_<symbol>_M5.csv
run_backtest.py        2) backtest           -> reports/summary.txt, trades.csv, equity.png
run_live.py            3) live signals from MT5 (console + Telegram). Never places orders
goldbot/
  data/                mt5_source.py (your broker), dukascopy.py, store.py
  smc/                 swings, structure (BOS/CHoCH), fvg, order_block, liquidity, sessions, indicators
  strategy/            asian_sweep.py  - the signal rules (liquidity sweep model)
  backtest/            engine.py (fills, SL/TP, spread, break-even, partials), report.py
  signals/             notifier.py (Telegram)
research/              experiments.py, combos.py, deep_test.py (variant grid + walk-forward)
tests/test_smc.py      unit tests + look-ahead test
```

## How to use

```powershell
.\.venv\Scripts\activate

# 1. Get data from MT5 (open MT5 and log in first)
python run_download.py --source mt5 --start 2023-01-01
python run_download.py --source mt5 --symbol XAGUSD    # silver, for SMT divergence

# 2. Backtest
python run_backtest.py

# 3. Tests
python -m tests.test_smc

# 4. Research: 320 variants + walk-forward (~1-2 minutes)
python -m research.deep_test

# 5. Live signals (MT5 must be open and logged in)
python run_live.py
```

### Telegram alerts (optional)
1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.
3. Put both values in `config.yaml` under `live:`, or set the env vars `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

### News filter
NFP (first Friday, 08:30 NY) is blocked automatically. To block other events, add rows to
`data/news_events.csv` (UTC times), for example:
```
datetime_utc,event
2026-10-28 18:00,FOMC
```

## Reading the backtest
- **Out-of-sample** = the last 30% of data. If results are good in-sample but bad out-of-sample, the settings are overfit.
- Judge **profit factor** (> 1.3 is good), **avg R** and **max drawdown**, not only win rate.
- The engine is conservative: spread is included, the stop wins if SL and TP are hit in the same candle,
  and no profit is taken on the fill candle.

## Roadmap
1. ✅ Rule engine + backtest + deep test
2. Forward-test `run_live.py` on an MT5 demo account for at least 2–4 weeks
3. Collect 300+ signals, then train an ML filter (XGBoost) on the feature columns in `trades.csv`
