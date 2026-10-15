"""Would scalping work on a low-cost (raw spread + commission) account?  python -m research.scalping_low_cost"""
import itertools

import pandas as pd

from goldbot.config import load_config, resolve
from research.scalping_test import context, evaluate, generate, load_m1


def main():
    cfg = load_config()
    m1 = load_m1()
    ctx = context(m1, cfg)
    weeks = (m1.index[-1] - m1.index[0]).days / 7
    rows = []
    for concept, rr in itertools.product(["micro_ict", "ema_pullback", "bos_fvg"], [1.0, 1.5, 2.0]):
        sig = generate(m1, ctx, concept, rr)
        for cost in (0.08, 0.15, 0.30):
            r = evaluate(sig, m1, cfg, cost)
            rows.append(dict(setup=concept, rr=rr, cost=cost, per_week=round(r["all"]["n"] / weeks, 1), win=r["all"]["win"],
                             PF=r["all"]["PF"], R=r["all"]["R"], PF_2324=r["train"]["PF"], PF_2025=r["valid"]["PF"], PF_2026=r["test"]["PF"]))
        print("done", concept, rr, flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(resolve("research/scalping_low_cost_results.csv"), index=False)
    pd.set_option("display.width", 200)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
