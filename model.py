"""
Forecast engine, fully parameterized so backtest.py can replay past elections.

polls -> weighted aggregate (recency + sample + house effects, with
below-threshold imputation) -> correlated Monte Carlo -> Bader-Ofer per sim.
"""
import json
from datetime import datetime

import numpy as np
import pandas as pd

from bader_ofer import allocate

# ----------------------------- DEFAULT CONFIG ------------------------------
HALF_LIFE_DAYS = 4    # backtest-calibrated (2021+2022)
WINDOW_DAYS = 90
N_SIMS = 20_000
SYSTEMATIC_SD = 0.012      # backtest-calibrated: 80% intervals cover ~85%
BLOC_SWING_SD = 0.008
BT_IMPUTE = 0.025          # share assigned when a poll lists a party as "-"
                           # (below threshold) rather than a number

# --- 2026 live config (edit as the campaign evolves) ---
BLOCS_2026 = {
    "coalition": ["Likud", "Shas", "UTJ", "RZP", "Otzma", "Zionist Home"],
    "opposition": ["Together", "Yashar", "Dems", "Yisrael Beiteinu",
                   "Blue & White", "Yesh Atid", "Bennett 2026"],
    "arab": ["Ra'am", "Hadash -Ta'al", "Balad"],
}
AGREEMENTS_2026 = [
    ("Likud", "RZP"), ("Shas", "UTJ"), ("Otzma", "Zionist Home"),
    ("Together", "Yashar"), ("Dems", "Yisrael Beiteinu"),
]

# Sector-bias prior, learned on 2019a/2019b/2020 and validated blind on
# 2021/2022 (sector_bias.py). Applied at 0.3 shrinkage — the full correction
# overfits an era; 0.3 balances seat-MAE against bloc-total bias.
SECTOR_2026 = {
    "Likud": "likud", "Shas": "haredi", "UTJ": "haredi",
    "Ra'am": "arab", "Hadash -Ta'al": "arab", "Balad": "arab",
    "RZP": "right", "Otzma": "right", "Zionist Home": "right",
    "Yisrael Beiteinu": "right",
}
SECTOR_CORRECTION = {"arab": 0.0078, "centerleft": -0.0044,
                     "haredi": 0.0132, "likud": 0.0351, "right": -0.0255}
CORRECTION_SHRINK = 0.3


def apply_sector_correction(mu, parties):
    import numpy as _np
    by_sec = {}
    for p in parties:
        by_sec.setdefault(SECTOR_2026.get(p, "centerleft"), []).append(p)
    delta = _np.array([
        CORRECTION_SHRINK
        * SECTOR_CORRECTION.get(SECTOR_2026.get(p, "centerleft"), 0.0)
        / len(by_sec[SECTOR_2026.get(p, "centerleft")])
        for p in parties])
    mu2 = _np.clip(mu + delta, 1e-4, None)
    return mu2 / mu2.sum()
# ---------------------------------------------------------------------------


def load_polls(path: str, as_of=None, window: int = WINDOW_DAYS,
               presence_days: int = 30, presence_min: float = 0.2):
    """Polls up to `as_of`, within `window` days back.
    Party set = parties appearing in >presence_min of the last presence_days."""
    df = pd.read_csv(path, parse_dates=["date"])
    as_of = pd.Timestamp(as_of) if as_of is not None else df["date"].max()
    df = df[(df["date"] <= as_of) &
            (df["date"] >= as_of - pd.Timedelta(days=window))].copy()
    recent = df[df["date"] >= as_of - pd.Timedelta(days=presence_days)]
    candidates = [c for c in df.columns
                  if c not in ("date", "pollster", "publisher", "sample")]
    parties = [p for p in candidates
               if len(recent) and recent[p].notna().mean() > presence_min]
    return df, parties


def poll_weights(df, half_life=HALF_LIFE_DAYS):
    age = (df["date"].max() - df["date"]).dt.days.to_numpy(float)
    w_recency = 0.5 ** (age / half_life)
    w_sample = np.sqrt(df["sample"].fillna(500).to_numpy(float) / 600.0).clip(0.5, 1.5)
    return w_recency * w_sample


def to_shares(df, parties):
    """Seats -> shares. A NaN for a party that runs in this period usually means
    'below threshold' in that poll, so impute BT_IMPUTE instead of dropping."""
    seats = df[parties].copy()
    imputed = seats.isna()
    shares = seats.fillna(0.0)
    tot = shares.sum(axis=1).replace(0, np.nan)
    shares = shares.div(tot, axis=0)
    shares[imputed] = BT_IMPUTE
    return shares.div(shares.sum(axis=1), axis=0)


def house_effects(df, shares, parties):
    ref = (shares.set_axis(df["date"]).sort_index().rolling("21D").mean())
    dev = shares.set_axis(df["date"]).sort_index() - ref
    dev["pollster"] = df.sort_values("date")["pollster"].to_numpy()
    he = dev.groupby("pollster")[parties].mean()
    n = dev.groupby("pollster").size()
    return he * (n / (n + 4)).to_numpy()[:, None]


def aggregate(df, parties):
    w = poll_weights(df)
    shares = to_shares(df, parties)
    he = house_effects(df, shares, parties)
    corr = shares.to_numpy().copy()
    for i, pollster in enumerate(df["pollster"]):
        if pollster in he.index:
            corr[i] -= he.loc[pollster].to_numpy()
    mu = (corr * w[:, None]).sum(axis=0) / w.sum()
    n_eff = w.sum() ** 2 / (w ** 2).sum()
    se = np.sqrt(np.maximum(mu, 1e-4) * (1 - mu) / 700) / np.sqrt(max(n_eff, 1))
    return mu, se


def simulate(mu, se, parties, blocs, agreements,
             n_sims=N_SIMS, systematic_sd=SYSTEMATIC_SD,
             bloc_swing_sd=BLOC_SWING_SD, seed=42):
    def bloc_of(p):
        return next((b for b, ms in blocs.items() if p in ms), "other")

    rng = np.random.default_rng(seed)
    k = len(parties)
    bloc_names = sorted({bloc_of(p) for p in parties})
    B = np.array([[1.0 if bloc_of(p) == b else 0.0 for b in bloc_names]
                  for p in parties])
    sd = np.sqrt(se ** 2 + systematic_sd ** 2 * mu / mu.mean())
    z = rng.standard_normal((n_sims, len(bloc_names))) * bloc_swing_sd
    shares = np.clip(mu + rng.standard_normal((n_sims, k)) * sd + z @ B.T,
                     1e-4, None)
    shares /= shares.sum(axis=1, keepdims=True)
    seats = np.zeros((n_sims, k), dtype=int)
    for s in range(n_sims):
        alloc = allocate(dict(zip(parties, shares[s])), agreements)
        seats[s] = [alloc[p] for p in parties]
    return shares, seats, bloc_of


def summarize(parties, shares, seats, bloc_of):
    out = {"generated": datetime.now().isoformat(timespec="seconds"),
           "n_sims": int(seats.shape[0]), "parties": [], "blocs": {}}
    for i, p in enumerate(parties):
        s = seats[:, i]
        out["parties"].append({
            "party": p, "bloc": bloc_of(p),
            "expected_seats": round(float(s.mean()), 1),
            "interval_80": [int(np.percentile(s, 10)), int(np.percentile(s, 90))],
            "p_pass_threshold": round(float((s > 0).mean()), 3),
            "mean_share": round(float(shares[:, i].mean()), 4)})
    for b in {bloc_of(p) for p in parties}:
        idx = [i for i, p in enumerate(parties) if bloc_of(p) == b]
        tot = seats[:, idx].sum(axis=1)
        out["blocs"][b] = {
            "expected_seats": round(float(tot.mean()), 1),
            "interval_80": [int(np.percentile(tot, 10)), int(np.percentile(tot, 90))],
            "p_61": round(float((tot >= 61).mean()), 3)}
    return out


def main():
    df, parties = load_polls("polls.csv")
    print(f"Using {len(df)} polls, {len(parties)} parties")
    mu, se = aggregate(df, parties)
    mu = apply_sector_correction(mu, parties)
    shares, seats, bloc_of = simulate(mu, se, parties,
                                      BLOCS_2026, AGREEMENTS_2026)
    forecast = summarize(parties, shares, seats, bloc_of)
    json.dump(forecast, open("forecast.json", "w"),
              ensure_ascii=False, indent=2)
    for r in sorted(forecast["parties"], key=lambda r: -r["expected_seats"]):
        print(f'{r["party"]:<18} {r["expected_seats"]:>5}  '
              f'80%: {r["interval_80"]}  P(pass)={r["p_pass_threshold"]:.0%}')
    print()
    for b, d in forecast["blocs"].items():
        print(f'{b:<11} {d["expected_seats"]:>6}  80%: {d["interval_80"]}  '
              f'P(>=61)={d["p_61"]:.0%}')


if __name__ == "__main__":
    main()
