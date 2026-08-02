"""
Sector-bias study, done properly (no data leakage):

TRAIN on 2019a / 2019b / 2020:
    measure how final-3-week poll aggregates missed each SECTOR
    (haredi / arab / likud / other-right / center-left).

TEST on 2021 / 2022:
    apply the learned sector corrections to the blind backtest and
    measure whether MAE / bloc error actually improve out-of-sample.
"""
import numpy as np
import pandas as pd

import model
from backtest import ELECTIONS, run_once

SECTOR = {
    # haredi
    "Shas": "haredi", "UTJ": "haredi",
    # arab lists (various incarnations)
    "Joint List": "arab", "Hadash -Ta'al": "arab", "Ra'am -Balad": "arab",
    "Ra'am": "arab", "Balad": "arab",
    # likud
    "Likud": "likud",
    # other right
    "URWP": "right", "New Right": "right", "Yamina": "right",
    "Otzma": "right", "Otzma Yehudit": "right", "Zehut": "right",
    "RZP- OY": "right", "Religious Zionist[a]": "right", "New Hope": "right",
    "Yisrael Beiteinu": "right",
    # center-left
    "Blue & White": "centerleft", "Kulanu": "centerleft",
    "Yesh Atid": "centerleft", "National Unity": "centerleft",
    "Labor": "centerleft", "Meretz": "centerleft", "Gesher": "centerleft",
    "Labor- Gesher": "centerleft", "Dem. Union": "centerleft",
    "Emet": "centerleft",
}

# actual VOTE SHARES (passing parties: seats/120-share of passing votes is a
# good proxy; failed parties: their official vote share)
TRAIN = {
    "2019a": {"polls": "polls2019a.csv", "eday": "2019-04-09", "actual_share": {
        "Likud": 35/120, "Blue & White": 35/120, "Shas": 8/120, "UTJ": 8/120,
        "Hadash -Ta'al": 6/120, "Labor": 6/120, "Yisrael Beiteinu": 5/120,
        "URWP": 5/120, "Meretz": 4/120, "Kulanu": 4/120, "Ra'am -Balad": 4/120,
        "New Right": 0.0322, "Zehut": 0.0274}},
    "2019b": {"polls": "polls2019b.csv", "eday": "2019-09-17", "actual_share": {
        "Blue & White": 33/120, "Likud": 32/120, "Joint List": 13/120,
        "Shas": 9/120, "Yisrael Beiteinu": 8/120, "UTJ": 7/120,
        "Yamina": 7/120, "Labor- Gesher": 6/120, "Dem. Union": 5/120,
        "Otzma Yehudit": 0.0188}},
    "2020": {"polls": "polls2020.csv", "eday": "2020-03-02", "actual_share": {
        "Likud": 36/120, "Blue & White": 33/120, "Joint List": 15/120,
        "Shas": 9/120, "UTJ": 7/120, "Emet": 7/120,
        "Yisrael Beiteinu": 7/120, "Yamina": 6/120, "Otzma": 0.0043}},
}


def poll_aggregate_shares(cfg):
    """Final-day blind aggregate (same machinery as the live model)."""
    as_of = pd.Timestamp(cfg["eday"]) - pd.Timedelta(days=1)
    df, parties = model.load_polls(cfg["polls"], as_of=as_of)
    parties = [p for p in parties if p in cfg["actual_share"]]
    mu, _ = model.aggregate(df, parties)
    return dict(zip(parties, mu))


def main():
    # ---------- TRAIN ----------
    per_election = []
    print("TRAIN — sector error (actual share - poll share), percentage points")
    for name, cfg in TRAIN.items():
        agg = poll_aggregate_shares(cfg)
        err = {}
        for sec in set(SECTOR.values()):
            members = [p for p in agg if SECTOR.get(p) == sec]
            if not members:
                continue
            poll_s = sum(agg[p] for p in members)
            act_s = sum(cfg["actual_share"][p] for p in members)
            err[sec] = act_s - poll_s
        per_election.append(err)
        print(f"  {name}: " + "  ".join(
            f"{s}={v*100:+.1f}" for s, v in sorted(err.items())))

    sectors = sorted({s for e in per_election for s in e})
    correction = {s: float(np.mean([e[s] for e in per_election if s in e]))
                  for s in sectors}
    print("\nLearned correction (pp): " +
          "  ".join(f"{s}={v*100:+.1f}" for s, v in correction.items()))

    # ---------- TEST out-of-sample on 2021 / 2022 ----------
    print("\nTEST — blind final-day backtest, uncorrected vs corrected")
    print(f'{"election":<22} | {"MAE raw":>7} {"MAE corr":>8} | '
          f'{"bloc raw":>8} {"bloc corr":>9}')
    for name, cfg in ELECTIONS.items():
        raw = run_once(cfg, 1, 0.009)
        # build per-party share deltas: sector correction split evenly
        parties = raw["parties"]
        by_sec = {}
        for p in parties:
            by_sec.setdefault(SECTOR.get(p, "other"), []).append(p)
        delta = np.zeros(len(parties))
        for i, p in enumerate(parties):
            sec = SECTOR.get(p, "other")
            if sec in correction:
                delta[i] = correction[sec] / len(by_sec[sec])

        as_of = pd.Timestamp(cfg["eday"]) - pd.Timedelta(days=1)
        df, _ = model.load_polls(cfg["polls"], as_of=as_of)
        mu, se = model.aggregate(df, parties)
        mu2 = np.clip(mu + delta, 1e-4, None)
        mu2 /= mu2.sum()
        _, seats, _ = model.simulate(mu2, se, parties, cfg["blocs"],
                                     cfg["agreements"], n_sims=10_000,
                                     systematic_sd=0.009)
        actual = raw["actual"]
        mae2 = float(np.abs(seats.mean(0) - actual).mean())
        bibi_idx = [i for i, p in enumerate(parties)
                    if p in cfg["blocs"]["netanyahu"]]
        bibi_err2 = float(seats[:, bibi_idx].sum(1).mean()
                          - cfg["netanyahu_actual"])
        print(f'{name:<22} | {raw["mae"]:>7.2f} {mae2:>8.2f} | '
              f'{raw["bibi_err"]:>+8.1f} {bibi_err2:>+9.1f}')

    print("\nCorrection dict for model.py (share deltas per sector):")
    print({s: round(v, 4) for s, v in correction.items()})


if __name__ == "__main__":
    main()
