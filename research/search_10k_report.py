"""Past-only ranking, cost checks, uncertainty, and review for the 10k search."""
import json
import math

import numpy as np
import pandas as pd
import yaml

from research.search_10k import OUT, BUILD, PARAMS, run_engine, hash_file, fold_ids


def aggregate(raw, meta):
    out = raw[["id"]].copy()
    for name, folds in [("train", [0, 1]), ("validation", [2, 3, 4, 5]), ("test", [6, 7]), ("all", list(range(8)))]:
        days = sum(meta["fold_days"][str(i)] for i in folds)
        for key in ["n", "wins", "sum", "positive", "negative", "sq", "signals", "signal_days", "fill_days", "purged"]:
            out[f"{name}_{key}"] = raw[[f"f{i}_{key}" for i in folds]].sum(axis=1)
        n, total, sq = (out[f"{name}_{key}"] for key in ["n", "sum", "sq"])
        out[f"{name}_avg_R"] = total/n.replace(0, np.nan)
        out[f"{name}_PF"] = out[f"{name}_positive"]/out[f"{name}_negative"].replace(0, np.nan)
        out[f"{name}_win_pct"] = 100*out[f"{name}_wins"]/n.replace(0, np.nan)
        out[f"{name}_fills_per_week"] = 5*n/days
        out[f"{name}_signals_per_week"] = 5*out[f"{name}_signals"]/days
        out[f"{name}_coverage_pct"] = 100*out[f"{name}_fill_days"]/days
        out[f"{name}_signal_coverage_pct"] = 100*out[f"{name}_signal_days"]/days
        variance = ((sq-total*total/n.replace(0, np.nan))/(n-1).replace(0, np.nan)).clip(lower=0)
        out[f"{name}_mean_R_lcb95"] = out[f"{name}_avg_R"]-1.96*np.sqrt(variance/n.replace(0, np.nan))
        p, z = out[f"{name}_wins"]/n.replace(0, np.nan), 1.96
        den = 1+z*z/n.replace(0, np.nan)
        centre = (p+z*z/(2*n.replace(0, np.nan)))/den
        delta = z*np.sqrt(p*(1-p)/n.replace(0, np.nan)+z*z/(4*n.replace(0, np.nan)**2))/den
        out[f"{name}_win_ci_low"] = 100*(centre-delta)
        out[f"{name}_win_ci_high"] = 100*(centre+delta)
    out["positive_train_years"] = (raw.f0_sum > 0).astype(int)+(raw.f1_sum > 0).astype(int)
    out["positive_validation_quarters"] = sum((raw[f"f{i}_sum"] > 0).astype(int) for i in [2, 3, 4, 5])
    out["enough_trades"] = (out.train_n >= 100) & (out.validation_n >= 50)
    out["frequency_target"] = (out.train_coverage_pct >= 50) & (out.validation_coverage_pct >= 50)
    out["high_win_target"] = (out.train_win_pct >= 55) & (out.validation_win_pct >= 55)
    out["profitable_selection"] = (out.train_PF >= 1.1) & (out.validation_PF >= 1.1)
    out["stable_selection"] = (out.positive_train_years == 2) & (out.positive_validation_quarters >= 3)
    out["qualifies_selection"] = out.enough_trades & out.frequency_target & out.high_win_target & out.profitable_selection & out.stable_selection
    out["score"] = out[["train_mean_R_lcb95", "validation_mean_R_lcb95"]].min(axis=1)
    return out


def choose(a):
    selection = {}
    masks = {
        "requested_target": a.qualifies_selection,
        "frequency_compromise": a.enough_trades & a.frequency_target,
        "profitable_compromise": a.enough_trades & a.profitable_selection & a.stable_selection,
        "high_win_compromise": a.enough_trades & a.high_win_target,
    }
    for name, mask in masks.items():
        rows = a[mask].sort_values(["score", "validation_n"], ascending=False)
        if len(rows):
            selection[name] = int(rows.iloc[0].id)
    supported = a[a.enough_trades].sort_values("score", ascending=False)
    best_by_family = supported.groupby("family", sort=False).head(1)
    return selection, best_by_family


def bootstrap_diagnostic(raw, meta, selected):
    # Selection-adjusted max statistic over ALL 10k models. 3-month circular blocks.
    cols = [f"month_{i}" for i, month in enumerate(meta["months"]) if month < "2026-01"]
    matrix = raw[cols].to_numpy().T
    means, sd = matrix.mean(axis=0), matrix.std(axis=0, ddof=1)
    se = sd/np.sqrt(len(matrix))
    valid = se > 1e-12
    centred = matrix-matrix.mean(axis=0)
    rng = np.random.default_rng(20261015)
    repetitions, months = 2000, len(matrix)
    counts = np.zeros((repetitions, months))
    for b in range(repetitions):
        starts = rng.integers(0, months, size=(months+2)//3)
        block = ((starts[:, None]+np.arange(3)) % months).ravel()[:months]
        counts[b] = np.bincount(block, minlength=months)/months
    simulated = (counts @ centred[:, valid])/se[valid]
    max_stat = simulated.max(axis=1)
    result = {"method": "Exploratory centred monthly max-t bootstrap, circular blocks of 3 months; all 10000 searches included",
              "limitations": "Only 36 selection months; not a proof of stationarity, independent test data, or a formal calibrated trading-system guarantee",
              "repetitions": repetitions, "selection_months": months, "selected": {}}
    for label, trial in selected.items():
        j = int(raw.index[raw.id == trial][0])
        observed = float(means[j]/se[j]) if valid[j] else 0
        adjusted = float((1+np.sum(max_stat >= observed))/(repetitions+1))
        result["selected"][label] = dict(id=trial, observed_monthly_t=observed, max_search_adjusted_p=adjusted)
    return result


def detail_metrics(path, f):
    t = pd.read_csv(path)
    active = t[(t.fill_i >= 0) & ~t.outcome.str.startswith("end_censored")].copy()
    days = f.loc[f.weekday < 5, "day"].drop_duplicates().sort_values()
    if len(active):
        r = active.r.to_numpy()
        cum = np.r_[0, np.cumsum(r)]
        fill_days = set(f.day.iloc[active.fill_i].tolist())
        streak = longest = 0
        for d in days:
            streak = 0 if d in fill_days else streak+1
            longest = max(longest, streak)
        dd = float((np.maximum.accumulate(cum)-cum).max())
    else:
        longest, dd = len(days), 0
    return dict(max_no_fill_trading_days=int(longest), max_drawdown_R=dd,
                fully_target_exits=int(active.outcome.str.startswith("tp").sum()),
                positive_trades=int((active.r > 0).sum()), filled=len(active),
                outcome_counts=t.outcome.value_counts().to_dict())


def finish():
    meta = json.loads((OUT / "metadata.json").read_text())
    raw = pd.read_csv(OUT / "raw_results.csv")
    configs = pd.read_csv(OUT / "configurations.csv")
    assert len(raw) == 10000 and raw.id.nunique() == 10000 and len(configs) == 10000
    assert hash_file(BUILD / "GoldSearch.exe")
    a = configs.merge(aggregate(raw, meta), on="id", validate="one_to_one")
    a.to_csv(OUT / "ranked_results.csv", index=False)
    selection, family_best = choose(a)
    (OUT / "selection.json").write_text(json.dumps(selection, indent=2), encoding="utf-8")
    family_best.to_csv(OUT / "best_by_family.csv", index=False)
    a[a.qualifies_selection].sort_values("score", ascending=False).to_csv(OUT / "qualified_selection.csv", index=False)
    # Stability checks evaluate close neighbours WITHOUT choosing a new winner on 2026.
    candidates = sorted(set(selection.values()) | set(family_best.id.astype(int)))
    params = configs[configs.id.isin(candidates)]
    params[PARAMS].to_csv(BUILD / "shortlist.csv", index=False)
    stress = []
    scenarios = [("minimum_spread", 0.3, 0.05, 0), ("base", 0.6, 0.1, 0),
                 ("wide_spread", 0.9, 0.15, 0), ("reported_half_cent_if_1oz", 0.6, 0.1, 0.005),
                 ("extra_fee_0p10_per_oz", 0.6, 0.1, 0.1)]
    for name, spread, slip, fee in scenarios:
        output = OUT / f"stress_{name}.csv"
        detail = OUT / "shortlist_detail" if name == "base" else None
        run_engine(BUILD / "shortlist.csv", output, spread, slip, fee, detail)
        part = aggregate(pd.read_csv(output), meta)
        part["scenario"], part["spread"], part["slippage"], part["fee_per_oz"] = name, spread, slip, fee
        stress.append(part)
    pd.concat(stress, ignore_index=True).to_csv(OUT / "stress_results.csv", index=False)
    uncertainty = bootstrap_diagnostic(raw, meta, selection)
    (OUT / "multiple_search_diagnostic.json").write_text(json.dumps(uncertainty, indent=2), encoding="utf-8")
    f = pd.read_pickle(BUILD / "features.pkl")
    from research.search_10k_sensitivity import perform
    perform(a, raw, meta, params, selection, f)
    additional = {}
    for trial in candidates:
        additional[str(trial)] = detail_metrics(OUT / f"shortlist_detail_{trial}.csv", f)
    (OUT / "shortlist_details.json").write_text(json.dumps(additional, indent=2), encoding="utf-8")
    for label, trial in selection.items():
        row = configs[configs.id == trial].iloc[0].to_dict()
        # Required explicit gate: this config cannot be passed to the live runner accidentally.
        evaluation = a[a.id == trial].iloc[0]
        payload = dict(status="RESEARCH ONLY - failed the complete requested target", search_id=int(trial),
                       algorithm_parameters=row, account=meta["broker"], costs=meta["primary_costs"],
                       engine="research/GoldSearch.cs", timestamp_status=meta["timestamp_status"],
                       selection=label, evaluated_2026=dict(PF=float(evaluation.test_PF),
                       win_pct=float(evaluation.test_win_pct), fills_per_week=float(evaluation.test_fills_per_week)),
                       deploy=False)
        (OUT / f"{label}.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    export_value_audit(f, configs, candidates, meta)
    # Time-forward selection uses only each preceding period and records an abstention if none pass.
    walk = []
    for year in [2025, 2026]:
        pool = a[(a.train_n >= 100) & (a.train_coverage_pct >= 50)] if year == 2025 else a[a.enough_trades & a.frequency_target]
        rank = "train_mean_R_lcb95" if year == 2025 else "score"
        if len(pool):
            best = pool.sort_values(rank, ascending=False).iloc[0]
            period = "validation" if year == 2025 else "test"
            walk.append(dict(year=year, id=int(best.id), family=best.family,
                             decision="research evaluation only; not an automatic deployment", n=best[f"{period}_n"],
                             win_pct=best[f"{period}_win_pct"], PF=best[f"{period}_PF"],
                             net_R=best[f"{period}_sum"], coverage_pct=best[f"{period}_coverage_pct"]))
    pd.DataFrame(walk).to_csv(OUT / "walk_forward.csv", index=False)
    report(a, raw, meta, selection, family_best, pd.concat(stress), uncertainty, additional)
    audit_files = ["configurations.csv", "raw_results.csv", "ranked_results.csv", "sources.json",
                   "engine_verification.json", "causality_checks.json", "all_cost_scenarios_summary.csv"]
    meta["final_artifact_sha256"] = {name: hash_file(OUT / name) for name in audit_files if (OUT / name).exists()}
    meta["live_config_unchanged"] = meta["config_sha256"] == hash_file(OUT.parent.parent / "config.yaml")
    meta["final_code_sha256"] = {path.name: hash_file(path) for path in (OUT.parent.parent / "research").glob("search_10k*.py")}
    (OUT / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("SELECTION", json.dumps(selection), flush=True)
    print("QUALIFIED", int(a.qualifies_selection.sum()), "/", len(a), flush=True)


def export_value_audit(f, configs, candidates, meta):
    labels = json.loads((OUT / "sources.json").read_text())
    folds = fold_ids(f.day)
    bias_names = {0: "none", 1: "H1_BOS", 2: "H1_HHHL", 3: "M15_BOS", 4: "M15_HHHL"}
    for trial in candidates:
        p = configs[configs.id == trial].iloc[0].to_dict()
        label = labels[int(p["source"])]
        decoded = dict(algorithm=label["family"], source_settings=label["settings"], bias=bias_names[p["bias"]],
                       session_NY=[f"{int(p['start'])//60:02d}:{int(p['start'])%60:02d}", f"{int(p['end'])//60:02d}:{int(p['end'])%60:02d}"],
                       stop_rule="structural extreme plus buffer" if p["stop_mode"] == 0 else f"{p['stop_mode']/2:g} ATR plus buffer",
                       management={0: "fixed target", 1: "BE at +1R", 2: "half at +1R and BE"}[p["management"]])
        payload = dict(status="UNQUALIFIED RESEARCH - not a live config", deploy=False, id=int(trial),
                       decoded=decoded, parameters=p, costs=meta["primary_costs"], account=meta["broker"])
        (OUT / f"candidate_{trial}.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        t = pd.read_csv(OUT / f"shortlist_detail_{trial}.csv")
        source_i = t.signal_i.to_numpy(int)
        fields = ["open", "high", "low", "close", "atr", "rsi", "adx", "body", "volratio",
                  "h1_bos", "h1_hhhl", "m15_bos", "m15_hhhl"]
        n = label["settings"].get("swing_n", label["settings"].get("m5_swing_n", 2))
        fields += [f"s{n}_{key}" for key in ["high", "previous_high", "high_label", "low", "previous_low", "low_label", "trend"]]
        for field in fields:
            t[f"known_{field}"] = f[field].to_numpy()[source_i]
        t["signal_time_UTC"] = f.close_time.to_numpy()[source_i]
        t["signal_bar_open_UTC"] = f.index[source_i]
        for kind in ["fill", "exit"]:
            t[f"{kind}_bar_open_UTC"] = [f.index[int(i)] if i >= 0 else pd.NaT for i in t[f"{kind}_i"]]
        t["planned_risk_usd_per_oz"] = (t.entry-t.sl)*t.d
        t["planned_reward_risk"] = (t.tp-t.entry)*t.d/t.planned_risk_usd_per_oz
        t["actual_fill_risk_usd_per_oz"] = np.where(t.fill_i >= 0, (t.fill_price-t.sl)*t.d, np.nan)
        t["included_in_fold_metrics"] = [i >= 0 and folds[int(i)] == int(fold) and not outcome.startswith("end_censored")
                                          for i, fold, outcome in zip(t.exit_i, t.fold, t.outcome)]
        if label["family"] == "ema_pullback":
            for name in ["fast", "slow"]:
                length = label["settings"][name]
                t[f"known_ema_{length}"] = f.close.ewm(span=length, adjust=False, min_periods=length).mean().to_numpy()[source_i]
        t.to_csv(OUT / f"candidate_{trial}_price_values.csv", index=False)


def report(a, raw, meta, selection, family_best, stress, uncertainty, details):
    # Filled in from saved measurements; no guessed performance figures.
    lines = ["# XAUUSD 10,000-configuration research — 15 October 2026", "",
             "Exactly 10,000 distinct parameter sets were evaluated: 1,000 for each of ten algorithm families, using deterministic random search (seed 20261015). Indicators and raw setup sources were computed once; each configuration reran setup filters, daily limits, pending/position capacity, trade execution, stops, targets, and management. This is not 10,000 resamples of one backtest. Selected models were rerun under five cost scenarios.", "",
             f"Data: {meta['bars']:,} cached broker M5 bars, {meta['start']} through {meta['end']}. Raw historical prices are used. The CSV has no historical bid/ask spread series, commission, swap, account identity, or contract specification. Cached symbol XAUUSD is not sufficient to establish Exness XAUUSDc provenance. The search does not fabricate those missing fields.", "",
             "## Broker and costs", "",
             "User account: Exness MT5 Standard Cent, leverage 1:2000, reported minimum spread 0.30, and reported 0.50 cent round-trip charge per lot. Official Exness Standard Cent terms describe no trading commission, cent balances, and a -c symbol suffix. The exact account charge and cent-lot contract specification remain unverified. A 0.50 USC round trip is USD 0.005 per cent lot, not USD 0.50; cost per ounce equals 0.005 divided by ounces per cent lot. Do not substitute standard-lot contract size without checking MT5 Specification.", "",
             "Primary selection scenario: spread $0.60/oz, slippage $0.10/oz at market entries and stop/timed exits, and zero trading commission under official Standard Cent terms. The $0.30/$0.05 and $0.90/$0.15 scenarios test the reported minimum and wider costs. Extra fees $0.005/oz (only if one cent lot equals one ounce) and $0.10/oz are sensitivities. Minimum advertised pips are not automatically USD-per-ounce price spread. Leverage changes margin, not forecast accuracy or expected R. No claim is made about margin feasibility or cent-lot rounding.", "",
             "Sources: [Exness Standard Cent](https://get.exness.help/hc/en-us/articles/17537782786588-Standard-Cent-account), [Exness metals specifications](https://get.exness.help/hc/en-us/articles/17854173039388-Commodities), [MT5 symbol information](https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py).", "",
             "## What was searched", "",
             "HH/HL confirmed-pivot pullbacks and BOS at pivot sizes 2–5; EMA recrosses 9/21, 13/34, 21/55, 34/89, 50/200; sweep/reclaim and Donchian breaks over 12/24/48/96 bars; RSI periods 7/14/21 and reversal levels 20/25/30/35; Bollinger 20/40 bars and 1.5/2/2.5 population standard deviations; three Silver Bullet windows; opening ranges beginning 08:20/08:30/09:30 NY, lasting 15/30 minutes, with edge or mid-retest entry; and H1/M15/M5 zone confluence with market/limit entries.", "",
             "The random search also varies H1/M15 BOS/HHHL bias or no bias, sessions, BUY/SELL/both, 1–3 setups/day, 6/12/24-bar cooldown, structural or ATR stops, ATR buffers 0.1–0.75, price risk minimum $1/$2/$3, maximum 4/6/8 ATR, expiry 30/60/120 minutes, hold 2/4/8 hours, ADX/volatility/candle-body filters, FVG/displacement thresholds and confluence flags. Targets: 0.75, 1, 1.25, 1.5, 2, 2.5 or 3R. Management: plain exit, move to BE at +1R, or close half at +1R and move remaining stop to BE. Partial/BE is disabled when the final target is at or below +1R.", "",
             "The grid covers a finite random subset, not all combinations or a global optimum. Some different settings can produce identical trades or no trades; 10,000 parameter vectors are distinct, not necessarily 10,000 statistically independent strategies.", "",
             "## Selection and results", "",
             "Training uses NY calendar years 2023–2024, validation uses four separate 2025 quarters, and final chronological evaluation uses 2026 H1/H2 through 14 October. Configs are ranked only on training/validation. Require at least 100 training fills and 50 validation fills. The requested target additionally requires fills on at least half of available trading days, at least 55% positive net trades, PF at least 1.10 in training AND validation, both training years profitable, and at least three profitable validation quarters. Rank by the smaller training/validation lower confidence bound on mean R. Trade confidence bounds are a screening statistic, not search-adjusted proof.", "",
             f"Qualified on the selection rules: {int(a.qualifies_selection.sum())} of 10,000. Supported by minimum trade counts: {int(a.enough_trades.sum())}. Meeting cadence before profitability gates: {int((a.enough_trades & a.frequency_target).sum())}.", "",
             "| Past-selected label | ID | Algorithm | Train PF | 2025 PF | 2026 PF | 2026 wins | 2026 fills/week | 2026 filled days |",
             "|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for label, trial in selection.items():
        r = a[a.id == trial].iloc[0]
        lines.append(f"| {label} | {trial} | {r.family} | {r.train_PF:.2f} | {r.validation_PF:.2f} | {r.test_PF:.2f} | {r.test_win_pct:.1f}% | {r.test_fills_per_week:.2f} | {r.test_coverage_pct:.1f}% |")
    if (OUT / "all_cost_scenarios_summary.csv").exists():
        lines += ["", "The same 10,000 configurations were additionally rerun at minimum and wider spreads: 30,000 full-history evaluations in total, before shortlist and neighbour diagnostics. No extra settings were chosen from 2026.", "",
                  "| Full-grid cost scenario | Spread / slippage | Configurations | Pass full selection target |", "|---|---|---:|---:|"]
        for r in pd.read_csv(OUT / "all_cost_scenarios_summary.csv").itertuples():
            lines.append(f"| {r.scenario} | {r.spread:.2f} / {r.slippage:.2f} | {r.configs} | {r.qualifies_selection} |")
    lines += ["", "Labels denote research selection criteria, not recommendations. A 'frequency compromise' can still lose; a 'profitable compromise' can be too infrequent. Final-period failure must not trigger choosing a replacement using the same final-period results.", "",
              "## Best supported candidate per family", "",
              "| Family | ID | Train PF | 2025 PF | 2026 PF | Overall fills/week | Overall wins |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for r in family_best.itertuples():
        lines.append(f"| {r.family} | {r.id} | {r.train_PF:.2f} | {r.validation_PF:.2f} | {r.test_PF:.2f} | {r.all_fills_per_week:.2f} | {r.all_win_pct:.1f}% |")
    lines += ["", "## Selected cost sensitivity", "",
              "| ID | Scenario | Train PF | 2025 PF | 2026 PF | 2026 net R |",
              "|---:|---|---:|---:|---:|---:|"]
    for r in stress[stress.id.isin(selection.values())].itertuples():
        lines.append(f"| {r.id} | {r.scenario} | {r.train_PF:.2f} | {r.validation_PF:.2f} | {r.test_PF:.2f} | {r.test_sum:+.1f} |")
    if (OUT / "neighbour_summary.csv").exists():
        lines += ["", "## Nearby values and hypothetical time offsets", "",
                  "These diagnostics perturb shortlisted parameters without selecting a replacement based on 2026. Neighbours change one of buffer, RR, session start/end, ADX threshold, hold or daily cap. Target-adjacent management is disabled when RR falls to 1 or less.", "",
                  "| ID | Neighbours | Profitable train AND validation | Profitable 2026 | 2026 PF range |",
                  "|---:|---:|---:|---:|---|" ]
        for r in pd.read_csv(OUT / "neighbour_summary.csv").itertuples():
            lines.append(f"| {r.id} | {r.neighbours} | {r.positive_train_validation_pct:.1f}% | {r.positive_test_pct:.1f}% | {r.test_PF_min:.2f}–{r.test_PF_max:.2f} |")
        lines += ["", "The +2h/+3h experiments below are hypothetical timestamp sensitivities, not verified corrections. Entry clocks, news masks, weekday/fold mapping and opening ranges are rebuilt. Non-timed price triggers and complete H1/M15 alignment are invariant to integer-hour shifts by construction. The selected parameter values are held fixed.", "",
                  "| ID | Hypothetical hours added | Train PF | 2025 PF | 2026 PF |", "|---:|---:|---:|---:|---:|"]
        for r in pd.read_csv(OUT / "timestamp_sensitivity.csv").itertuples():
            lines.append(f"| {r.id} | {r.hypothetical_offset_hours} | {r.train_PF:.2f} | {r.validation_PF:.2f} | {r.test_PF:.2f} |")
    lines += ["", "## Are the values correct?", "",
              "No strategy is assumed correct merely because it wins a search. Independent Python parity passed on 23 nonempty sampled configurations and 8,253 accepted setups, comparing prices, outcomes, capacity, and net R to 1e-8. Twelve hand-calculated engine tests passed, including partial/BE timing, ask exits, fees and gaps. All 54 source variants passed three truncated-history comparisons each (162 checks), and indicators matched their full-history prefixes. engine_verification.json and causality_checks.json preserve the evidence. These finite checks do not prove an absence of all defects.", "",
              "Every shortlisted candidate has candidate_ID_price_values.csv with the actual known OHLC, ATR, RSI, ADX, volatility, confirmed high/low prices and labels, entry, stop, target, fills and realised R. candidate_ID.yaml decodes source settings and parameter units and explicitly disables deployment. Exit bar timestamps identify OHLC bars; precise intrabar fill/exit times are unknown.", "",
              "Confirmed pivots become available only at pivot+n candle close. HH and HL compare consecutive same-side confirmed pivots with an explicit $0.01 tolerance; equal pivots are neutral. H1/M15 bias is aligned only after the higher-timeframe candle closes. ATR14 is recursively seeded from first TR; ADX14 uses exponentially smoothed directional movements; rolling volatility compares ATR against its preceding/current 288-bar rolling mean. These causal definitions are explicit research conventions and may differ from a platform's initialisation. All inputs and source settings are exported.", "",
              "One slot permits either a pending order or an open position. Limits require bid/ask touch; markets execute at the next open within five minutes. Pending orders cancel if a blackout starts before fill. Stop-first ambiguous bars, no fill-bar profit taking, next-bar BE activation, gap-aware adverse stops, and nonpositive fill-risk rejection are enforced. Timed exits across a missing-bar gap use the first available open after the deadline, not a retrospective stale close. Dataset-end censored trades and trades crossing fold boundaries are excluded from fold performance. Such fills still occupy capacity while they exist. Spread is fixed per scenario, not observed tick spread.", "",
              "Net R uses actual fill-to-original-stop price risk and includes realised partial profits, remaining-size exit, slippage and per-ounce commission. A partial-then-BE trade can be positive, and is not a full-target hit. A stop loss can exceed 1R after gaps/fees. Prices are rounded to cents as represented in the cache; Exness's actual tick size, stop levels, trade mode and volume step still require platform verification. Swap is not modelled; overnight/rollover exposures must be checked before live use.", "",
              "## Timestamp and provenance limitation", "",
              "The current downloader subtracts an inferred server offset before labelling the data UTC. Official MT5 copy_rates_range documentation says returned bars are UTC without a shift. That discrepancy means session hours/news alignment in the existing cache are not independently established. The terminal was not available for a live match during this run. Any candidate remains provisional; shifting timestamps back mechanically is not a validated correction. Selected timestamp sensitivity checks are recorded separately if available.", "",
              "Source: [MT5 copy_rates_range timestamp documentation](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py).", "",
              "## Search bias and uncertainty", "",
              "All historical years were exposed by prior project research; 2026 is not pristine independent data. More trials increase the chance of finding accidental winners. A centred monthly max-t bootstrap with 3-month circular blocks includes all 10,000 primary trials as an exploratory multiple-search diagnostic, using 2023–2025 only. It does not certify a future edge or remove nonstationarity, historical reuse, provider mismatch, or model misspecification.", ""]
    for label, r in uncertainty["selected"].items():
        lines.append(f"- {label} #{r['id']}: approximate max-search-adjusted p={r['max_search_adjusted_p']:.3f}.")
    lines += ["", "Research basis: [Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).", "",
              "## Decision and reproducibility", "",
              "Do not select by win rate alone, overwrite the live config automatically, or claim leverage will improve edge. Use the exported parameters only for research until frequency, measured Exness costs, price/timestamp provenance, quarter/year stability, parameter-neighbour sensitivity and fresh forward outcomes support deployment. No orders, Telegram messages or account changes were made. Original live config is preserved.", "",
              "Run: python -m research.search_10k prepare; python -m research.search_10k_verify; python -m research.search_10k run; python -m research.search_10k finish. The C# source compiles locally with the Windows .NET compiler and has no trading/network APIs. configurations.csv and raw_results.csv contain all 10,000 trials. ranked_results.csv contains derived metrics and gates; sources.json documents the 54 setup sources; metadata.json records hashes, data period, costs and limitations. Research YAMLs are not live-runner configs."]
    lines += ["", "Additional reproducible checks: python -m tests.test_search_10k; python -m research.search_10k_causality; python -m research.search_10k_cost_sweep. Run finish again after the cost sweep to include all-grid sensitivity counts in the review. For independent verification, run search_10k_verify before accepting results, and preserve metadata plus the cached data hash."]
    (OUT / "review.md").write_text("\n".join(lines), encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 6))
    supported = a[a.enough_trades]
    scatter = ax.scatter(supported.validation_coverage_pct, supported.validation_win_pct,
                         c=supported.validation_avg_R, cmap="RdYlGn", vmin=-0.3, vmax=0.2, alpha=0.5, s=12)
    ax.axvline(50, ls="--", color="navy")
    ax.axhline(55, ls="--", color="navy")
    for label, trial in selection.items():
        r = a[a.id == trial].iloc[0]
        ax.scatter(r.validation_coverage_pct, r.validation_win_pct, facecolors="none", edgecolors="black", s=90)
        ax.annotate(f"#{trial}", (r.validation_coverage_pct, r.validation_win_pct), xytext=(5, 5), textcoords="offset points")
    ax.set(xlabel="2025 trading days with fills (%)", ylabel="2025 positive net trades (%)", title="10,000 settings: supported candidates in 2025")
    fig.colorbar(scatter, ax=ax, label="2025 mean net R")
    fig.tight_layout()
    fig.savefig(OUT / "comparison.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    finish()
