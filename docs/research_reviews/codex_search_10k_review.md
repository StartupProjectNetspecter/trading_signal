# XAUUSD 10,000-configuration research — 15 October 2026

Exactly 10,000 distinct parameter sets were evaluated: 1,000 for each of ten algorithm families, using deterministic random search (seed 20261015). Indicators and raw setup sources were computed once; each configuration reran setup filters, daily limits, pending/position capacity, trade execution, stops, targets, and management. This is not 10,000 resamples of one backtest. Selected models were rerun under five cost scenarios.

Data: 266,410 cached broker M5 bars, 2023-01-02 23:00:00+00:00 through 2026-10-14 17:35:00+00:00. Raw historical prices are used. The CSV has no historical bid/ask spread series, commission, swap, account identity, or contract specification. Cached symbol XAUUSD is not sufficient to establish Exness XAUUSDc provenance. The search does not fabricate those missing fields.

## Broker and costs

User account: Exness MT5 Standard Cent, leverage 1:2000, reported minimum spread 0.30, and reported 0.50 cent round-trip charge per lot. Official Exness Standard Cent terms describe no trading commission, cent balances, and a -c symbol suffix. The exact account charge and cent-lot contract specification remain unverified. A 0.50 USC round trip is USD 0.005 per cent lot, not USD 0.50; cost per ounce equals 0.005 divided by ounces per cent lot. Do not substitute standard-lot contract size without checking MT5 Specification.

Primary selection scenario: spread $0.60/oz, slippage $0.10/oz at market entries and stop/timed exits, and zero trading commission under official Standard Cent terms. The $0.30/$0.05 and $0.90/$0.15 scenarios test the reported minimum and wider costs. Extra fees $0.005/oz (only if one cent lot equals one ounce) and $0.10/oz are sensitivities. Minimum advertised pips are not automatically USD-per-ounce price spread. Leverage changes margin, not forecast accuracy or expected R. No claim is made about margin feasibility or cent-lot rounding.

Sources: [Exness Standard Cent](https://get.exness.help/hc/en-us/articles/17537782786588-Standard-Cent-account), [Exness metals specifications](https://get.exness.help/hc/en-us/articles/17854173039388-Commodities), [MT5 symbol information](https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py).

## What was searched

HH/HL confirmed-pivot pullbacks and BOS at pivot sizes 2–5; EMA recrosses 9/21, 13/34, 21/55, 34/89, 50/200; sweep/reclaim and Donchian breaks over 12/24/48/96 bars; RSI periods 7/14/21 and reversal levels 20/25/30/35; Bollinger 20/40 bars and 1.5/2/2.5 population standard deviations; three Silver Bullet windows; opening ranges beginning 08:20/08:30/09:30 NY, lasting 15/30 minutes, with edge or mid-retest entry; and H1/M15/M5 zone confluence with market/limit entries.

The random search also varies H1/M15 BOS/HHHL bias or no bias, sessions, BUY/SELL/both, 1–3 setups/day, 6/12/24-bar cooldown, structural or ATR stops, ATR buffers 0.1–0.75, price risk minimum $1/$2/$3, maximum 4/6/8 ATR, expiry 30/60/120 minutes, hold 2/4/8 hours, ADX/volatility/candle-body filters, FVG/displacement thresholds and confluence flags. Targets: 0.75, 1, 1.25, 1.5, 2, 2.5 or 3R. Management: plain exit, move to BE at +1R, or close half at +1R and move remaining stop to BE. Partial/BE is disabled when the final target is at or below +1R.

The grid covers a finite random subset, not all combinations or a global optimum. Some different settings can produce identical trades or no trades; 10,000 parameter vectors are distinct, not necessarily 10,000 statistically independent strategies.

## Selection and results

Training uses NY calendar years 2023–2024, validation uses four separate 2025 quarters, and final chronological evaluation uses 2026 H1/H2 through 14 October. Configs are ranked only on training/validation. Require at least 100 training fills and 50 validation fills. The requested target additionally requires fills on at least half of available trading days, at least 55% positive net trades, PF at least 1.10 in training AND validation, both training years profitable, and at least three profitable validation quarters. Rank by the smaller training/validation lower confidence bound on mean R. Trade confidence bounds are a screening statistic, not search-adjusted proof.

Qualified on the selection rules: 0 of 10,000. Supported by minimum trade counts: 4134. Meeting cadence before profitability gates: 1280.

| Past-selected label | ID | Algorithm | Train PF | 2025 PF | 2026 PF | 2026 wins | 2026 fills/week | 2026 filled days |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| frequency_compromise | 37 | hhhl_pullback | 0.77 | 0.90 | 0.90 | 53.1% | 5.54 | 82.4% |
| profitable_compromise | 729 | hhhl_pullback | 1.20 | 1.99 | 0.35 | 20.0% | 1.59 | 30.9% |
| high_win_compromise | 2103 | ema_pullback | 0.85 | 1.39 | 0.66 | 49.0% | 2.40 | 43.1% |

The same 10,000 configurations were additionally rerun at minimum and wider spreads: 30,000 full-history evaluations in total, before shortlist and neighbour diagnostics. No extra settings were chosen from 2026.

| Full-grid cost scenario | Spread / slippage | Configurations | Pass full selection target |
|---|---|---:|---:|
| minimum_spread | 0.30 / 0.05 | 10000 | 0 |
| wide_spread | 0.90 / 0.15 | 10000 | 0 |
| base | 0.60 / 0.10 | 10000 | 0 |

Labels denote research selection criteria, not recommendations. A 'frequency compromise' can still lose; a 'profitable compromise' can be too infrequent. Final-period failure must not trigger choosing a replacement using the same final-period results.

## Best supported candidate per family

| Family | ID | Train PF | 2025 PF | 2026 PF | Overall fills/week | Overall wins |
|---|---:|---:|---:|---:|---:|---:|
| hhhl_pullback | 729 | 1.20 | 1.99 | 0.35 | 1.62 | 43.7% |
| ema_pullback | 2317 | 1.16 | 1.41 | 0.68 | 1.24 | 49.4% |
| opening_range | 7940 | 1.16 | 1.32 | 1.26 | 1.19 | 43.6% |
| silver_bullet | 6551 | 0.97 | 1.00 | 0.80 | 2.81 | 53.9% |
| bollinger_reentry | 5361 | 1.03 | 1.32 | 1.17 | 1.25 | 51.2% |
| donchian | 8887 | 0.78 | 0.91 | 0.68 | 4.32 | 41.8% |
| bos | 1110 | 0.89 | 0.88 | 0.72 | 3.45 | 55.2% |
| sweep_reclaim | 3234 | 0.90 | 1.11 | 0.89 | 5.39 | 27.9% |
| rsi_reversal | 4579 | 0.77 | 1.10 | 0.67 | 1.32 | 47.9% |
| mtf_confluence | 9835 | 0.93 | 1.04 | 1.36 | 1.40 | 51.4% |

## Selected cost sensitivity

| ID | Scenario | Train PF | 2025 PF | 2026 PF | 2026 net R |
|---:|---|---:|---:|---:|---:|
| 37 | minimum_spread | 0.93 | 1.00 | 0.94 | -5.0 |
| 729 | minimum_spread | 1.55 | 2.05 | 0.36 | -28.5 |
| 2103 | minimum_spread | 1.01 | 1.53 | 0.69 | -14.8 |
| 37 | base | 0.77 | 0.90 | 0.90 | -8.2 |
| 729 | base | 1.20 | 1.99 | 0.35 | -29.1 |
| 2103 | base | 0.85 | 1.39 | 0.66 | -16.2 |
| 37 | wide_spread | 0.64 | 0.81 | 0.87 | -11.2 |
| 729 | wide_spread | 1.02 | 1.81 | 0.33 | -30.8 |
| 2103 | wide_spread | 0.72 | 1.26 | 0.63 | -17.6 |
| 37 | reported_half_cent_if_1oz | 0.77 | 0.89 | 0.90 | -8.2 |
| 729 | reported_half_cent_if_1oz | 1.20 | 1.99 | 0.35 | -29.2 |
| 2103 | reported_half_cent_if_1oz | 0.85 | 1.38 | 0.66 | -16.2 |
| 37 | extra_fee_0p10_per_oz | 0.73 | 0.87 | 0.89 | -9.1 |
| 729 | extra_fee_0p10_per_oz | 1.15 | 1.95 | 0.35 | -29.4 |
| 2103 | extra_fee_0p10_per_oz | 0.81 | 1.35 | 0.65 | -16.6 |

## Nearby values and hypothetical time offsets

These diagnostics perturb shortlisted parameters without selecting a replacement based on 2026. Neighbours change one of buffer, RR, session start/end, ADX threshold, hold or daily cap. Target-adjacent management is disabled when RR falls to 1 or less.

| ID | Neighbours | Profitable train AND validation | Profitable 2026 | 2026 PF range |
|---:|---:|---:|---:|---|
| 37 | 13 | 0.0% | 0.0% | 0.82–0.94 |
| 729 | 13 | 84.6% | 0.0% | 0.31–0.48 |
| 2103 | 14 | 0.0% | 0.0% | 0.56–0.75 |
| 5361 | 14 | 78.6% | 100.0% | 1.10–1.53 |
| 7940 | 14 | 100.0% | 92.9% | 0.89–1.54 |

The +2h/+3h experiments below are hypothetical timestamp sensitivities, not verified corrections. Entry clocks, news masks, weekday/fold mapping and opening ranges are rebuilt. Non-timed price triggers and complete H1/M15 alignment are invariant to integer-hour shifts by construction. The selected parameter values are held fixed.

| ID | Hypothetical hours added | Train PF | 2025 PF | 2026 PF |
|---:|---:|---:|---:|---:|
| 37 | 0 | 0.77 | 0.90 | 0.90 |
| 729 | 0 | 1.20 | 1.99 | 0.35 |
| 2103 | 0 | 0.85 | 1.39 | 0.66 |
| 5361 | 0 | 1.03 | 1.32 | 1.17 |
| 7940 | 0 | 1.16 | 1.32 | 1.26 |
| 37 | 2 | 0.79 | 0.86 | 0.96 |
| 729 | 2 | 0.92 | 1.22 | 0.44 |
| 2103 | 2 | 0.80 | 0.97 | 0.55 |
| 5361 | 2 | 0.78 | 0.99 | 1.57 |
| 7940 | 2 | 0.92 | 0.79 | 0.30 |
| 37 | 3 | 0.76 | 0.81 | 0.88 |
| 729 | 3 | 0.88 | 1.00 | 0.46 |
| 2103 | 3 | 0.72 | 0.84 | 0.65 |
| 5361 | 3 | 0.64 | 1.04 | 1.47 |
| 7940 | 3 | 0.73 | 0.57 | 0.61 |

## Are the values correct?

No strategy is assumed correct merely because it wins a search. Independent Python parity passed on 23 nonempty sampled configurations and 8,253 accepted setups, comparing prices, outcomes, capacity, and net R to 1e-8. Twelve hand-calculated engine tests passed, including partial/BE timing, ask exits, fees and gaps. All 54 source variants passed three truncated-history comparisons each (162 checks), and indicators matched their full-history prefixes. engine_verification.json and causality_checks.json preserve the evidence. These finite checks do not prove an absence of all defects.

Every shortlisted candidate has candidate_ID_price_values.csv with the actual known OHLC, ATR, RSI, ADX, volatility, confirmed high/low prices and labels, entry, stop, target, fills and realised R. candidate_ID.yaml decodes source settings and parameter units and explicitly disables deployment. Exit bar timestamps identify OHLC bars; precise intrabar fill/exit times are unknown.

Confirmed pivots become available only at pivot+n candle close. HH and HL compare consecutive same-side confirmed pivots with an explicit $0.01 tolerance; equal pivots are neutral. H1/M15 bias is aligned only after the higher-timeframe candle closes. ATR14 is recursively seeded from first TR; ADX14 uses exponentially smoothed directional movements; rolling volatility compares ATR against its preceding/current 288-bar rolling mean. These causal definitions are explicit research conventions and may differ from a platform's initialisation. All inputs and source settings are exported.

One slot permits either a pending order or an open position. Limits require bid/ask touch; markets execute at the next open within five minutes. Pending orders cancel if a blackout starts before fill. Stop-first ambiguous bars, no fill-bar profit taking, next-bar BE activation, gap-aware adverse stops, and nonpositive fill-risk rejection are enforced. Timed exits across a missing-bar gap use the first available open after the deadline, not a retrospective stale close. Dataset-end censored trades and trades crossing fold boundaries are excluded from fold performance. Such fills still occupy capacity while they exist. Spread is fixed per scenario, not observed tick spread.

Net R uses actual fill-to-original-stop price risk and includes realised partial profits, remaining-size exit, slippage and per-ounce commission. A partial-then-BE trade can be positive, and is not a full-target hit. A stop loss can exceed 1R after gaps/fees. Prices are rounded to cents as represented in the cache; Exness's actual tick size, stop levels, trade mode and volume step still require platform verification. Swap is not modelled; overnight/rollover exposures must be checked before live use.

## Timestamp and provenance limitation

The current downloader subtracts an inferred server offset before labelling the data UTC. Official MT5 copy_rates_range documentation says returned bars are UTC without a shift. That discrepancy means session hours/news alignment in the existing cache are not independently established. The terminal was not available for a live match during this run. Any candidate remains provisional; shifting timestamps back mechanically is not a validated correction. Selected timestamp sensitivity checks are recorded separately if available.

Source: [MT5 copy_rates_range timestamp documentation](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py).

## Search bias and uncertainty

All historical years were exposed by prior project research; 2026 is not pristine independent data. More trials increase the chance of finding accidental winners. A centred monthly max-t bootstrap with 3-month circular blocks includes all 10,000 primary trials as an exploratory multiple-search diagnostic, using 2023–2025 only. It does not certify a future edge or remove nonstationarity, historical reuse, provider mismatch, or model misspecification.

- frequency_compromise #37: approximate max-search-adjusted p=1.000.
- profitable_compromise #729: approximate max-search-adjusted p=0.877.
- high_win_compromise #2103: approximate max-search-adjusted p=1.000.

Research basis: [Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).

## Decision and reproducibility

Do not select by win rate alone, overwrite the live config automatically, or claim leverage will improve edge. Use the exported parameters only for research until frequency, measured Exness costs, price/timestamp provenance, quarter/year stability, parameter-neighbour sensitivity and fresh forward outcomes support deployment. No orders, Telegram messages or account changes were made. Original live config is preserved.

Run: python -m research.search_10k prepare; python -m research.search_10k_verify; python -m research.search_10k run; python -m research.search_10k finish. The C# source compiles locally with the Windows .NET compiler and has no trading/network APIs. configurations.csv and raw_results.csv contain all 10,000 trials. ranked_results.csv contains derived metrics and gates; sources.json documents the 54 setup sources; metadata.json records hashes, data period, costs and limitations. Research YAMLs are not live-runner configs.

Additional reproducible checks: python -m tests.test_search_10k; python -m research.search_10k_causality; python -m research.search_10k_cost_sweep. Run finish again after the cost sweep to include all-grid sensitivity counts in the review. For independent verification, run search_10k_verify before accepting results, and preserve metadata plus the cached data hash.