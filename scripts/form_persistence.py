"""Do hot streaks carry over? For skaters and goalies, regress the next stretch's performance above
their own norm on the last stretch's.

    python scripts/form_persistence.py

Slope 0 = streaks are pure noise; slope 1 = a heater carries over in full. Uses the same norms as
features/form.py, measured strictly before the game where the "next stretch" starts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yaml

from nhlmodel.config import repo_path
from nhlmodel.features.build import _read_seasons
from nhlmodel.features.form import SKATER_STATS, _league_rate_asof, skater_games
from nhlmodel.features.goalies import goalie_games_with_xg, league_offset

SEASONS = list(range(20112012, 20262027, 10001))
NEXT = 10


def fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float, int]:
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    slope = np.cov(x, y)[0, 1] / np.var(x, ddof=1)
    return slope, np.corrcoef(x, y)[0, 1], float(np.std(x)), len(x)


def skaters(games: pd.DataFrame, cfg: dict) -> list[dict]:
    sg = skater_games(_read_seasons("events", SEASONS), _read_seasons("xg", SEASONS), _read_seasons("rosters", SEASONS))
    p = sg.merge(games[["game_id", "start_time_utc"]], on="game_id").sort_values(["player_id", "start_time_utc"])
    p = p.reset_index(drop=True)
    league = _league_rate_asof(p, SKATER_STATS, "pos").fillna(0.0)
    h, k = cfg["baseline_halflife_games"], cfg["baseline_pseudo_games"]
    lam = 0.5 ** (1 / h)
    grp = p.groupby("player_id", sort=False)
    n_before = grp.cumcount().to_numpy()  # games before this one
    rows = []
    for c in SKATER_STATS:
        # norm as of BEFORE game i: decayed mean over games < i, shrunk to the league rate
        dmean = grp[c].transform(lambda s: s.shift(1).ewm(halflife=h).mean()).fillna(0).to_numpy()
        count = (1 - lam ** n_before) / (1 - lam)
        base = (dmean * count + k * league[c].to_numpy()) / (count + k)
        fut = grp[c].transform(lambda s: s[::-1].rolling(NEXT, min_periods=NEXT).mean()[::-1]).to_numpy()
        for w in cfg["windows"]:
            past = grp[c].transform(lambda s: s.shift(1).rolling(w, min_periods=w).mean()).to_numpy()
            keep = n_before >= 41  # an established norm
            s, r, sd, n = fit((past - base)[keep], (fut - base)[keep])
            rows.append({"who": "skater", "stat": c, "last_n": w, "slope": s, "corr": r, "sd_recent": sd, "n": n})
    return rows


def goalies(games: pd.DataFrame, gcfg: dict, cfg: dict) -> list[dict]:
    xg = _read_seasons("xg", SEASONS)
    gg = goalie_games_with_xg(xg, _read_seasons("goalie_games", SEASONS), games).reset_index(drop=True)
    gg = gg[gg["shots"] > 0].reset_index(drop=True)
    gsax = gg["xga"] - gg["ga"] - gg["shots"] * league_offset(gg, gcfg.get("league_prior_shots", 5000))
    p = gg["player_id"]
    shots = gg["shots"].astype(float)
    cum_g = gsax.groupby(p).cumsum() - gsax
    cum_s = shots.groupby(p).cumsum() - shots
    career = 100 * cum_g / (cum_s + gcfg["prior_shots"])  # before this appearance
    nxt = 5
    fg = gsax.groupby(p).transform(lambda s: s[::-1].rolling(nxt, min_periods=nxt).sum()[::-1])
    fs = shots.groupby(p).transform(lambda s: s[::-1].rolling(nxt, min_periods=nxt).sum()[::-1])
    fut = 100 * fg / fs - career
    rows = []
    for w in cfg["goalie_windows"]:
        rg = gsax.groupby(p).transform(lambda s: s.shift(1).rolling(w, min_periods=w).sum())
        rs = shots.groupby(p).transform(lambda s: s.shift(1).rolling(w, min_periods=w).sum())
        past = 100 * rg / rs - career
        keep = (cum_s >= 1500).to_numpy()  # about 50 starts of history
        s, r, sd, n = fit(past.to_numpy()[keep], fut.to_numpy()[keep])
        rows.append({"who": "goalie", "stat": "gsax100", "last_n": w, "slope": s, "corr": r, "sd_recent": sd, "n": n})
    return rows


def main() -> int:
    base = yaml.safe_load(open(repo_path("configs/features/base.yaml")))
    games = pd.read_parquet(repo_path("data/processed/games.parquet"))
    games = games[games["season"].isin(SEASONS)]
    out = pd.DataFrame(skaters(games, base["form"]) + goalies(games, base["goalies"], base["form"]))
    print(out.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    out.to_csv(repo_path("results/form_persistence.csv"), index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
