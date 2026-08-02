"""
Backtest the full pipeline "blind" on the 2021 and 2022 elections.

For each election and each freeze point (1/7/14/30 days before election day),
the model sees ONLY polls available at that date, produces a forecast, and is
scored against the official results:

  - MAE (seats)          — mean absolute error per party
  - bloc error           — error on pro-Netanyahu bloc total
  - 80% coverage         — how often the actual seats fell inside the 80% interval
                           (well-calibrated => ~80%)
  - Brier (threshold)    — mean (P(pass) - passed)^2 over threshold-risk parties

It also grid-searches SYSTEMATIC_SD to find the best-calibrated value.
"""
import numpy as np

import model

ELECTIONS = {
    "2021 (24th Knesset)": {
        "polls": "polls2021.csv",
        "eday": "2021-03-23",
        "actual": {"Likud": 30, "Yesh Atid": 17, "Shas": 9, "Blue & White": 8,
                   "Yamina": 7, "Labor": 7, "UTJ": 7, "Yisrael Beiteinu": 7,
                   "Religious Zionist[a]": 6, "Joint List": 6, "New Hope": 6,
                   "Meretz": 6, "Ra'am": 4},
        "agreements": [("Likud", "Religious Zionist[a]"), ("Shas", "UTJ"),
                       ("Yesh Atid", "Yisrael Beiteinu"),
                       ("Yamina", "New Hope"), ("Labor", "Meretz")],
        "blocs": {"netanyahu": ["Likud", "Shas", "UTJ", "Religious Zionist[a]"],
                  "anti": ["Yesh Atid", "Blue & White", "Labor", "Meretz",
                           "Yisrael Beiteinu", "New Hope"],
                  "unaligned": ["Yamina", "Ra'am", "Joint List"]},
        "netanyahu_actual": 52,
    },
    "2022 (25th Knesset)": {
        "polls": "polls2022.csv",
        "eday": "2022-11-01",
        "actual": {"Likud": 32, "Yesh Atid": 24, "RZP- OY": 14,
                   "National Unity": 12, "Shas": 11, "UTJ": 7,
                   "Yisrael Beiteinu": 6, "Ra'am": 5, "Hadash -Ta'al": 5,
                   "Labor": 4, "Meretz": 0, "Balad": 0},
        "agreements": [("Likud", "RZP- OY"), ("Shas", "UTJ"),
                       ("Yesh Atid", "National Unity"), ("Labor", "Meretz")],
        "blocs": {"netanyahu": ["Likud", "RZP- OY", "Shas", "UTJ"],
                  "anti": ["Yesh Atid", "National Unity", "Labor", "Meretz",
                           "Yisrael Beiteinu"],
                  "unaligned": ["Ra'am", "Hadash -Ta'al", "Balad",
                                "Joint List"]},
        "netanyahu_actual": 64,
    },
}

FREEZES = [30, 14, 7, 1]
SD_GRID = [0.006, 0.009, 0.012, 0.015]


def run_once(cfg, freeze_days, systematic_sd, n_sims=10_000):
    import pandas as pd
    as_of = pd.Timestamp(cfg["eday"]) - pd.Timedelta(days=freeze_days)
    df, parties = model.load_polls(cfg["polls"], as_of=as_of)
    # score only parties we know the true result for
    parties = [p for p in parties if p in cfg["actual"]]
    mu, se = model.aggregate(df, parties)
    _, seats, bloc_of = model.simulate(
        mu, se, parties, cfg["blocs"], cfg["agreements"],
        n_sims=n_sims, systematic_sd=systematic_sd)

    actual = np.array([cfg["actual"][p] for p in parties])
    exp = seats.mean(axis=0)
    lo = np.percentile(seats, 10, axis=0)
    hi = np.percentile(seats, 90, axis=0)
    mae = float(np.abs(exp - actual).mean())
    cover = float(((actual >= lo) & (actual <= hi)).mean())

    # threshold Brier over parties that were genuinely at risk in the sims
    p_pass = (seats > 0).mean(axis=0)
    passed = (actual > 0).astype(float)
    risk = (p_pass > 0.01) & (p_pass < 0.99)
    brier = float(((p_pass[risk] - passed[risk]) ** 2).mean()) if risk.any() else None

    bibi_idx = [i for i, p in enumerate(parties)
                if p in cfg["blocs"]["netanyahu"]]
    bibi = seats[:, bibi_idx].sum(axis=1)
    return {"n_polls": len(df), "parties": parties, "exp": exp,
            "lo": lo, "hi": hi, "actual": actual, "mae": mae,
            "coverage": cover, "brier": brier,
            "bibi_exp": float(bibi.mean()),
            "bibi_err": float(bibi.mean() - cfg["netanyahu_actual"]),
            "p_pass": p_pass}


def main():
    # ---- Part 1: calibrate SYSTEMATIC_SD on final-week forecasts ----
    print("=" * 66)
    print("PART 1 — SYSTEMATIC_SD calibration (freeze = 1 day out)")
    print("=" * 66)
    print(f'{"SD":>6} | {"MAE 2021":>8} {"MAE 2022":>8} | '
          f'{"cover 2021":>10} {"cover 2022":>10} | target cover 80%')
    best, best_score = None, 9e9
    for sd in SD_GRID:
        res = {name: run_once(cfg, 1, sd) for name, cfg in ELECTIONS.items()}
        maes = [r["mae"] for r in res.values()]
        covs = [r["coverage"] for r in res.values()]
        score = np.mean(maes) + 8 * abs(np.mean(covs) - 0.80)
        if score < best_score:
            best, best_score = sd, score
        print(f'{sd:>6} | {maes[0]:>8.2f} {maes[1]:>8.2f} | '
              f'{covs[0]:>10.0%} {covs[1]:>10.0%}')
    print(f"\n--> chosen SYSTEMATIC_SD = {best}")

    # ---- Part 2: full report at every freeze with the chosen SD ----
    for name, cfg in ELECTIONS.items():
        print("\n" + "=" * 66)
        print(f"PART 2 — {name}  (SYSTEMATIC_SD={best})")
        print("=" * 66)
        print(f'{"days out":>8} | {"polls":>5} | {"MAE":>5} | '
              f'{"80% cover":>9} | {"Brier":>6} | {"Bibi bloc err":>13}')
        for f in FREEZES:
            r = run_once(cfg, f, best)
            b = f'{r["brier"]:.3f}' if r["brier"] is not None else "  -  "
            print(f'{f:>8} | {r["n_polls"]:>5} | {r["mae"]:>5.2f} | '
                  f'{r["coverage"]:>9.0%} | {b:>6} | {r["bibi_err"]:>+13.1f}')

        r = run_once(cfg, 1, best)
        print(f'\nFinal-day forecast vs actual ({name}):')
        order = np.argsort(-r["exp"])
        for i in order:
            p = r["parties"][i]
            inside = "  " if r["lo"][i] <= r["actual"][i] <= r["hi"][i] else "<<"
            print(f'  {p:<22} pred {r["exp"][i]:>5.1f} '
                  f'[{int(r["lo"][i]):>2}-{int(r["hi"][i]):>2}]  '
                  f'actual {r["actual"][i]:>2} {inside}  '
                  f'P(pass)={r["p_pass"][i]:.0%}')
        print(f'  {"NETANYAHU BLOC":<22} pred {r["bibi_exp"]:>5.1f}          '
              f'actual {cfg["netanyahu_actual"]}')


if __name__ == "__main__":
    main()
