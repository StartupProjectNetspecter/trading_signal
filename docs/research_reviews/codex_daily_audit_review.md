# Gold daily-signal and calculation audit — 15 October 2026

No tested configuration establishes the requested combination of frequent trades, high win rate and positive cost-adjusted expectancy. Daily alerts are technically achievable; they are not a substitute for a profitable trading rule. Production config and live behaviour were preserved.

## Scope and decision rules

266,410 broker XAUUSD M5 bars, 2 January 2023 through 14 October 2026. Eight concept families, 360 primary settings, 16 adaptive 2R/3R follow-up settings, and one two-concept combination. Follow-up selection uses training/validation only. The existing liquidity-sweep model was reproduced separately.

Training: 2023–2024. Validation: 2025. Evaluation: 2026. Minimum selection support: 100 training fills and 50 validation fills. The requested cadence is operationalised as fills on at least 50% of available trading days in BOTH training and validation. High win rate is provisionally defined as at least 55% in both. Positive net mean R is required in both. ZERO of 360 primary variants meets all conditions. A 50% coverage threshold still does not guarantee a trade every second day; quiet streaks are reported separately.

All these years have been inspected in prior project research. 2026 is a chronological evaluation, not untouched out-of-sample evidence. Testing 360 configurations and adaptive follow-ups causes selection bias. No backtest can guarantee an error-free future prediction or a fixed win rate.

## Current production baseline

176 signals, 70 fills, 52.9% positive net trades, PF 1.38, +12.2R. About 0.36 fills/week and fills on 7.1% of available weekdays. Longest observed quiet streak: 62 trading days. It does not satisfy the desired cadence.
The baseline produced signals on 175 distinct NY weekdays out of 984 available weekdays (17.8%), approximately 0.89 signals/week. That is roughly one alert every 5.6 available trading days, versus the desired one alert every one or two trading days. Signals and filled trades are deliberately reported separately.

The 52.9% win rate counts any positive final R, including profits banked at a partial exit followed by a break-even stop. Only 26 of 70 fills ended at the final target with a partial, nine ended at break-even after a partial, and three timed out. It is not a 52.9% final-2R-target hit rate. Closing half at +1R and half at +2R yields +1.5R, not +2R. Current baseline metrics use its existing execution/management assumptions and are not an identical-execution comparison to the new research models.

## Best past-period score per concept

Rows are selected by the smaller of training and validation mean R, with minimum support. They are not selected by 2026 results. This displays each concept's strongest tested past-period compromise, including losing concepts.

| Concept | RR | Fills/week, all years | Win %, all years | PF 2023–24 | PF 2025 | PF 2026 |
|---|---:|---:|---:|---:|---:|---:|
| opening_range | 1.5 | 1.18 | 43.5 | 1.00 | 1.02 | 1.31 |
| bos | 1 | 8.71 | 48.5 | 0.90 | 0.91 | 0.76 |
| hhhl_pullback | 1 | 8.35 | 49.5 | 0.84 | 0.94 | 0.87 |
| silver_bullet | 1 | 2.33 | 44.2 | 0.83 | 0.87 | 0.58 |
| rsi_reversal | 1.5 | 2.53 | 39.4 | 0.84 | 0.88 | 0.78 |
| ema_pullback | 0.75 | 4.29 | 53.8 | 0.72 | 0.76 | 0.91 |
| sweep_reclaim | 1.5 | 8.09 | 39.1 | 0.78 | 0.80 | 0.91 |
| bollinger_reentry | 1.5 | 4.65 | 38.3 | 0.75 | 0.83 | 0.92 |

## Values worth researching, and values rejected

The marginally profitable primary opening-range candidate uses a complete 08:30–08:45 NY range, first breakout before 11:30, H1 BOS bias, limit entry halfway between range centre and broken edge, stop beyond the opposite range edge +0.2 ATR, target 1.5R, and 60-minute limit expiry. Opening-range width must be at most 6 ATR and trade price risk $1–8 ATR. Its primary result: 232 fills, 43.5% wins, PF 1.08 overall; 1.18 fills/week, only 23.6% of trading days, and a 20-trading-day quiet streak. Training PF 1.003 and validation PF 1.021 are almost break-even. At $0.60 spread plus $0.10 slippage, overall PF falls to 0.90. A hypothetical $0.10/oz round-trip commission makes training PF 0.95 and validation PF 0.99. It is a research candidate, not a deployment recommendation.

The highest-scoring frequent primary candidate is BOS, n=2, H1 BOS bias, 07:00–15:00 NY, +0.5 ATR stop buffer and 1R target. It averages 8.71 fills/week but loses in every chronological period. The highest-scoring primary candidate meeting 55% wins in training/validation uses BOS with no H1 filter, 02:00–15:00 NY, buffer 0.5 ATR and 0.75R target: 56.4% training wins and 59.9% validation wins, but training PF 0.83 and 2026 PF 0.87. At a 0.75R payoff the cost-free break-even win rate is 57.14%, and spread/slippage push the requirement higher. High win rate alone is insufficient.

Follow-ups at 2R/3R did not establish the requested combination. One HH/HL 3R follow-up is marginally profitable in training/validation but fails in 2026 (PF 0.88). Combining the two strongest past-period concepts, ORB and BOS, produces 8.25 fills/week but loses in all three periods (PF 0.88 / 0.90 / 0.83). Adding weak concepts to increase frequency does not rescue an edge.

## Exact higher-high/higher-low calculations

For pivot size n, compare high[j] with highs in [j−n, j+n], and low[j] with lows in that window. A pivot is available only after bar j+n CLOSES. At n=2 on M5 this is two further bars, or ten minutes after the pivot bar closes. Equal extremes use the first occurrence in the window; pivots are not assumed known at their original timestamp.

Compare consecutive confirmed highs: HH when new_high > previous_high + 0.01; LH when new_high < previous_high − 0.01; otherwise EH. Compare consecutive confirmed lows: HL when new_low > previous_low + 0.01; LL when new_low < previous_low − 0.01; otherwise EL. The $0.01 tolerance is an explicit research comparison convention, not a verified broker tick size. Bullish HH/HL state requires BOTH latest labels HH and HL; bearish requires BOTH LH and LL. Mixed or equal structures are neutral. This state is distinct from BOS direction; the existing live bias uses BOS direction.

Actual example known at 2026-10-14 03:45:00+00:00: high 4170.28 versus prior confirmed high 4163.41 -> HH; low 4163.24 versus prior confirmed low 4161.47 -> HL. Each pivot price, original timestamp, confirmation timestamp, prior value and label is exported in confirmed_structure_values.csv.

## Mathematical rules for every concept

| Concept | Closed-bar trigger | Stop reference before ATR buffer |
|---|---|---|
| HH/HL pullback | HH+HL state, newly confirmed swing low and bullish candle; mirror LH+LL for sells | Newly confirmed low/high |
| BOS | Candle closes beyond a last confirmed pivot, one event per broken pivot; both BOS and initial/changed-direction breaks allowed | Last confirmed opposite pivot |
| EMA pullback | EMA21 > EMA55 and close recrosses EMA21 upward after prior close below it, bullish candle; mirror sells | Lowest/highest of latest six bars |
| Sweep reclaim | Low breaches prior 12-bar low and closes back above it with bullish candle; mirror high reclaim | Sweep candle extreme |
| RSI reversal | Wilder-style RSI14 crosses up through 30 from below with bullish candle; mirror down through 70 | Six-bar extreme |
| Bollinger re-entry | Prior close below its 20-bar lower band and current close returns above its current band with bullish candle; mirror sells | Six-bar extreme |
| Silver Bullet approximation | Consecutive three-bar FVG ≥0.1 ATR; preceding candle body ≥0.5 ATR in gap direction; 03–04, 10–11, 14–15 NY | Three-bar extreme |
| Opening-range retest | Three complete 08:30/08:35/08:40 bars define range, first later close outside it | Opposite range edge |

ATR14: TR=max(high−low, abs(high−previous_close), abs(low−previous_close)); recursive ATR_t=ATR_(t−1)+(TR_t−ATR_(t−1))/14, initialised from the first TR and withheld until 14 bars. EMA alpha=2/(period+1), initialised from the first close. RSI uses recursively smoothed positive and negative close changes with alpha=1/14; RSI=100−100/(1+avg_gain/avg_loss), with explicit zero-loss/flat handling. Bollinger bands use mean20 ±2 population standard deviations (ddof=0). These initialisation choices are exact and can differ from other platforms' seed conventions. A long FVG is low[i] > high[i−2], a short FVG high[i] < low[i−2]. Entry is the midpoint of the gap. Short rules mirror long rules.

Grid: n=2/3 for swing concepts; none/H1 BOS/H1 HHHL bias; NY 07–15 or London+NY 02–15; stop buffers 0.2/0.5 ATR; RR 0.75/1/1.5. Follow-ups test 2R/3R on the past-selected base settings. Session membership and news decisions use signal CLOSE time. Weekends excluded. At most two setups/day and 12-bar cooldown; one setup per approved timed window. H1 bars require 12 M5 observations and are usable only at H1 close, never while forming. These windows are explicit research conventions, not a claim to implement every discretionary ICT rule.

For direction d=+1 BUY or −1 SELL: stop=stop_reference−d*buffer*ATR; price_risk=d*(entry−stop); target=entry+d*RR*price_risk. Prices are rounded to cents before risk checks. New research accepts price_risk ≥$1 and ≤8 ATR. Higher risk limits differ from the production 4-ATR bound and are recorded rather than silently treated as the same strategy.

## Execution and measurement

New-model base cost scenario: constant $0.30/oz spread; $0.05/oz slippage at market entry, stops and timed exits; no commission. These are assumptions, not measured broker costs. Stress scenarios use spread/slippage $0.60/$0.10 and $0.90/$0.15, plus a separate $0.10/oz round-trip commission scenario. Markets fill at the next available open within a five-minute expiry, buying at ask plus slippage and selling at bid minus slippage. Limits fill at the stated level only when ask lows/bid highs reach it. Setups opening beyond either bracket are rejected; nonpositive fill risk is rejected. Long exits use bid, short exits ask. Stop wins when stop and target both appear in one bar. Fill-bar targets are ignored. Stop gaps execute at the worse opening price with slippage. There are no partials or break-even moves in these new models.

Only one pending order or open position is allowed. Signals arriving while the slot is occupied are reported as capacity rejections. Pending expiry and eight-hour hold use elapsed time. Across missing bars, timed closure is approximated at the last available close before the deadline, which may not have been executable at the deadline. OHLC cannot recover tick order, bid/ask variability or queue position, so execution remains an approximation. News blocks setup generation; a previously placed pending order is not automatically cancelled when a later blackout starts. No simultaneous-position equity return is asserted.

Net R = (d*(exit−actual_fill)−round_trip_commission)/actual_fill_to_stop_risk. PF=sum(positive R)/abs(sum(negative R)); win rate=fraction with R>0. Filled-day coverage=distinct NY weekdays with a fill / distinct available weekdays. Fills/week=5*fills/available_weekdays, not an assumption of uniformly spaced trades. Boundary-crossing unresolved positions are excluded from the earlier selection period. A few partial data days remain in the weekday denominator. Rates refer to trading days rather than weekends. Saved signal tables also show unfilled and capacity-rejected setups.

## Uncertainty

Opening-range 2026 mean-R monthly block-bootstrap 95% interval: [-0.118, +0.440]. Zero is plausible. The bootstrap uses only ten calendar month blocks, one of them partial, and is not adjusted for strategy search. Win-rate Wilson intervals are saved for each period; they also do not correct for dependence/search. Statistical confidence is therefore weaker than simply quoting a backtest win percentage.

## Existing-code issues found

1. Existing Silver Bullet expiry scans forward to find the end of the window. Ten of twelve sampled legacy prefix checks differed. New expiry uses the scheduled clock end plus 30 minutes, so it is identical on truncated data.
2. Existing combined reversal/continuation generation computes all reversals for a day before earlier continuation candidates and shares the daily cap. A later reversal can consume capacity before an earlier continuation in some configurations. Twelve sampled combined-prefix checks passed on the current sample; the code ordering remains a conditional risk, not an observed failure in those samples.
3. Existing liquidity-target sorting chooses the farthest qualifying target for buys/sells despite its nearest-target comment. It also does not filter target availability positions. This affects liquidity TP variants with future London targets, not the current fixed-RR NY config.
4. Existing frequency and daily walk-forward scripts first filter candidates by frequency over all years, which leaks later-period frequency into candidate eligibility. Existing deep_test MANAGEMENT overrides do not consistently reset inherited partial/breakeven settings: a variant named 2R can still inherit current management. Those labels should not be assumed equivalent to explicit no-partial 2R. New models use plain fixed-R targets and explicit past-period eligibility.
5. Legacy engine has no guard for nonpositive gap-fill risk and charges partial trade commission using whole final-exit notional. Gold commission defaults to zero, so that fee error does not change the reproduced baseline. These concerns are avoided by the isolated new research engine rather than changing locked v1 behaviour.
6. News CSV is populated but omits the 12 January 2023 CPI release at 08:30 ET. Follow-up checks add it in a separate news_events_checked.csv. The entire calendar has not been independently verified; other major releases beyond NFP/CPI/PPI/FOMC remain outside its stated coverage. Sources: [BLS CPI archive](https://www.bls.gov/news.release/archives/cpi_01122023.htm), [BLS actual February 2026 NFP](https://www.bls.gov/news.release/archives/empsit_02112026.htm), [Federal Reserve calendars](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm).

## Verification and next action

Four existing sanity tests and the locked v1 regression passed. Fourteen new unit tests cover HH/HL/equal prices, every synthetic prefix, a nonempty complete opening range, bid/ask fills, gaps, nonpositive risk rejection, slippage, commission, stop-first ambiguity, capacity and elapsed expiry. Thirty-two full-vs-prefix signal checks passed across all eight new concepts, with feature equality checked separately. These sampled checks are evidence of correct implementation under the stated definitions, not a proof against every possible defect.

Do not change the live model to a losing high-frequency configuration. Preserve current signals, paper-track the ORB research candidate if desired, and collect actual bid/ask/fill costs plus news provenance. A future daily-frequency claim requires a fixed prospective rule, positive expectancy after measured costs, coverage and quiet-streak evidence, and uncertainty bounds. No final recommended live parameter set is justified by this audit.

Reproduce: python -m research.gold_daily_audit; python -m research.validate_daily; python -m research.supplement_daily; python -m research.report_daily. The optional --resume flag is only for the same data/config/code conventions. candidate_*.yaml and concept_configs.json are research parameters, NOT compatible live-bot deployment configs. All artifacts are local; no downloads, live orders or Telegram sends were performed.