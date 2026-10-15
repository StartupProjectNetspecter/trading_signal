"""Rerun the same 10,000 configs at optimistic and adverse spread scenarios."""
import json

import pandas as pd

from research.search_10k import OUT, run_engine
from research.search_10k_report import aggregate


def main():
    meta = json.loads((OUT / "metadata.json").read_text())
    primary = pd.read_csv(OUT / "ranked_results.csv")
    rows = []
    for name, spread, slippage in [("minimum_spread", 0.3, 0.05), ("wide_spread", 0.9, 0.15)]:
        path = OUT / f"all_10000_{name}_raw.csv"
        run_engine(output=path, spread=spread, slippage=slippage)
        a = aggregate(pd.read_csv(path), meta)
        a.to_csv(OUT / f"all_10000_{name}_metrics.csv", index=False)
        paired = a.merge(primary[["id", "qualifies_selection"]], on="id", suffixes=("", "_base"))
        rows.append(dict(scenario=name, spread=spread, slippage=slippage, configs=len(a),
                         enough_trades=int(a.enough_trades.sum()),
                         qualifies_selection=int(a.qualifies_selection.sum()),
                         qualifies_both_this_and_base=int((paired.qualifies_selection & paired.qualifies_selection_base).sum())))
    base = primary
    rows.append(dict(scenario="base", spread=0.6, slippage=0.1, configs=len(base),
                     enough_trades=int(base.enough_trades.sum()), qualifies_selection=int(base.qualifies_selection.sum()),
                     qualifies_both_this_and_base=int(base.qualifies_selection.sum())))
    pd.DataFrame(rows).to_csv(OUT / "all_cost_scenarios_summary.csv", index=False)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
