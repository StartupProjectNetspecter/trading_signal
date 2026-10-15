# Model and configuration review — 15 October 2026

The concept is a testable, rule-based Asian-range reversal strategy, not a trained ML model. The available evidence does not establish a reliable profitable configuration. Gold merits further paper research; BTC does not merit deployment with these rules and cost assumptions. Production configurations were left unchanged.

## What was tested

53 distinct configurations: 26 gold and 27 BTC. Comparisons cover entry model, HTF bias/timeframe, session, RR, stop buffer, entry level, sweep depth, displacement, swing size, expiry, midnight filter and liquidity targets, plus a small predefined NY/OB/RR/buffer grid. This is a bounded search, not an exhaustive global optimum.

Chronological periods: training 2023–2024; validation 2025; evaluation 2026 through each dataset's last bar. Trades crossing selection boundaries are excluded from the earlier period. Ranking uses the lower of training and validation mean R, with at least 20 training fills and 10 validation fills. These thresholds are minimal screening rules, not evidence of statistical significance. No eligible candidate has a positive score. Rankings use rounded report metrics.

Prior research chose improvements using BOTH IS and OOS, and existing reports exposed 2026. Consequently these historical periods are research data; the 2026 evaluation is not a pristine independent test. Fresh forward observations are required to establish an edge. Searching more parameters on these same trades increases selection bias.

## Results

R means net profit divided by entry-to-stop price risk. Fees can make a stop lose more than 1R. PF is gross positive R divided by gross negative R.

| Configuration | 2023–24 fills / net R | 2025 fills / net R | 2026 fills / net R | Overall PF |
|---|---:|---:|---:|---:|
| Gold current | 41 / +4.7 | 9 / −3.0 | 14 / +2.0 | 1.10 |
| Gold NY + OB + buffer 0.2 + RR 2 | 25 / +2.7 | 5 / +1.0 | 10 / +5.0 | 1.41 |
| Gold NY + OB + buffer 0.2 + RR 3 | 29 / +4.8 | 6 / +2.0 | 12 / +11.1 | 1.70 |
| BTC current | 36 / −17.0 | 11 / −11.4 | 10 / −3.8 | 0.42 |
| BTC OB entry | 21 / −9.9 | 14 / −6.3 | 9 / −8.9 | 0.43 |

Every tested BTC variant has negative training AND validation net R. BTC OB is the highest score under the minimum-count rule, but remains strongly losing; “highest ranked” does not mean suitable. Gold's highest score under that rule is FVG-then-OB: validation −0.2R and 2026 −3.1R, also unsuitable.

## Most promising gold values for paper research

Use `XAUUSD_paper_rr3.yaml` only as an exploratory candidate. Main differences from production:

```yaml
strategy:
  kill_zones: [newyork]
  entry_model: ob
  entry_price: ce
  htf_bias: structure
  htf_timeframe: 1h
  swing_n: 2
  htf_swing_n: 2
  sl_buffer_atr: 0.2
  rr: 3.0
  entry_expiry_bars: 12
backtest:
  risk_per_trade: 0.0025
```

The saved YAML contains the full config. The 0.25% risk is a discretionary paper sizing assumption, not an optimized source of trading edge. Retain RR 2 as a comparison; neither RR value is established as optimal. Keep current session hours, H1 structure and other settings fixed while collecting fresh evidence rather than adding more historical filters.

This RR 3 candidate has only 47 fills over nearly four years, including six validation fills. Overall mean R is +0.380, win rate 40.4%, net +17.9R, max R drawdown 9.2 and longest losing streak eight. An exploratory IID bootstrap gives a 95% mean-R interval of approximately −0.101 to +0.877: zero remains plausible even before adjusting for the search or trade dependence. This bootstrap is not a deployment test.

At spread $0.30, $0.60 and $0.90, overall PF falls from 1.70 to 1.32 to 1.21. Training performance becomes −4.3R at $0.60 and −7.2R at $0.90. Thus the attractive result is cost-sensitive and is heavily helped by 2026. Gold commission and additional execution slippage are absent from the current assumption and would further affect results. CSV return/drawdown percentages use the metrics helper's standard 1% risk; the paper YAML's 0.25% sizing is not reflected in those percentages.

## Concept and implementation findings

1. **BTC execution market mismatch.** Data is Binance spot, while the 0.04% fee comment refers to futures. Shorts require an execution product allowing short exposure. Spot candles with futures fees do not establish a futures result; futures also require relevant prices, funding and contract rules. At hypothetical 0.075% and 0.10% per-side fees, BTC OB 2026 net R worsens to −11.5 and −13.3, versus −8.9 at 0.04%. These are sensitivity scenarios, not verified account-specific rates. Binance documents account/symbol-specific commission queries: https://github.com/binance/binance-spot-api-docs/blob/master/faqs/commission_faq.md

2. **News filtering is incomplete.** `data/news_events.csv` has a header only, so CPI/FOMC and other supplied-calendar events are absent. NFP is approximated as the first Friday and can miss actual releases. For example BLS published January 2026 employment on February 11, not the first Friday. Use archived actual release timestamps for historical tests and the official schedule for upcoming events: https://www.bls.gov/news.release/archives/empsit_02112026.pdf and https://www.bls.gov/schedule/news_release/empsit.htm . News and kill-zone masks use candle OPEN timestamps while the signal is known at candle CLOSE, creating a five-minute boundary discrepancy.

3. **The CHoCH label is broader than a confirmed trend reversal.** The strategy freezes a swing level at the first sweep and tests a later close beyond it. It does not require a prior opposite M5 trend. Sweep and break may occur within the same candle. A wick beyond the range is sufficient; a close back inside is not explicitly required. These are actual mathematical rules and should be the stated concept.

4. **Entry zones have limited validation.** FVG search does not check whether later bars already mitigated an older gap. OB selection is the last opposite-colour candle, and the search extends three bars before the sweep extreme. It does not require an additional volume or mitigation condition. These are hypotheses to evaluate separately, not assumptions that confer an edge.

5. **Backtest limitations.** Five-minute OHLC cannot resolve intrabar sequences or limit queue fills. Stop-first ties and ignoring fill-bar TP are conservative, but orders are considered filled on a touch with price improvement; an open beyond the stop is not rejected, and same-fill-bar stops always execute at the stop. A guard for nonpositive realized price risk and explicit gap execution rules would be needed for broader datasets. No such invalid realized risk occurred in the baseline audit. Simulated holding/expiry bars represent available bars rather than elapsed time, so gaps can extend actual holding duration. Portfolio equity assumes sequential compounding at exit and does not reserve equity at entry or cap concurrent exposure; no overlapping baseline positions were found in either dataset.

6. **Data and live behaviour.** Gold: 266,410 bars, 2023-01-02 through 2026-10-14; BTC: 397,986 bars, 2023-01-01 through 2026-10-13. Both are sorted, unique, have no missing values and no invalid OHLC relationships. Gold has 1,021 gaps longer than five minutes, including normal closures; BTC has one. This checks internal consistency, not broker timestamp correctness or full market coverage. Asian ranges accept 24 bars although the four-hour window normally contains 48. Partial sessions can therefore be accepted. BTC weekends are deliberately skipped by the shared strategy, despite its continuous market.

7. **Live configuration and documentation.** `run_live.py` loads gold config only and reads MT5. It does not run the Binance BTC config. BTC config retains `mt5_symbol: XAUUSD`, which would need correction in any future configurable live runner. README still describes FVG/fallback and 0.2 ATR while production gold uses OB and 0.5 ATR. The bot sends signals only and has no automated order lifecycle/cancellation management.

## Verification and next decision

Existing four sanity tests passed. Additional full-prefix equality checks passed at five distributed cut points for each baseline (10 checks). Rolling live-history comparisons reproduced all 34 gold and 33 BTC baseline signals in 2026 using the configured 1,728-bar lookback. These findings support causality at sampled points, not a proof for every possible configuration or market.

Recommended next decision: paper-test the fixed NY/OB gold candidate with RR 2 and RR 3 tracked separately; record executable bid/ask, actual broker fees, signals, fills, missed fills and order timing. Define acceptance criteria before collecting new outcomes, and require positive cost-adjusted expectancy supported by uncertainty analysis. The current trade frequency means strong statistical evidence may take a long time. Do not promote BTC or claim an ML filter can repair the edge on the present 57-fill sample.

Reproduce with `.venv/Scripts/python.exe -m research.deep_check` and `.venv/Scripts/python.exe -m research.verify_concept`. Raw variant tables, rankings, stress tests, baseline integrity evidence and candidate trades are stored beside this review. Production files and the original reports are unchanged.
