"""Goalie features for game G must not depend on goalie data from G or later.

The *actual*-starter variant reads G's post-game starter flag by design (documented leaky upper
bound), but the rating attached to that goalie must still come only from earlier games.
"""
import glob

import numpy as np
import pandas as pd
import pytest
import yaml

from nhlmodel.config import repo_path
from nhlmodel.features.goalies import goalie_features, goalie_games_with_xg

SEASONS = [20232024, 20242025]


@pytest.fixture(scope="module")
def data():
    paths = [repo_path(f"data/processed/goalie_games/{s}.parquet") for s in SEASONS]
    xg_paths = [repo_path(f"data/processed/xg/{s}.parquet") for s in SEASONS]
    if not all(p.exists() for p in paths + xg_paths):
        pytest.skip("processed goalie/xG data not present")
    cfg = yaml.safe_load(open(repo_path("configs/features/base.yaml")))["goalies"]
    games = pd.read_parquet(repo_path("data/processed/games.parquet"))
    games = games[games.season.isin(SEASONS)]
    gg = pd.concat([pd.read_parquet(p) for p in paths])
    xg = pd.concat([pd.read_parquet(p) for p in xg_paths])
    ggx = goalie_games_with_xg(xg, gg, games)
    base = goalie_features(ggx, games, cfg).set_index(["game_id", "team_id"]).sort_index()
    return cfg, games, ggx, base


def _scramble(ggx, t0, seed, flags):
    rng = np.random.default_rng(seed)
    out = ggx.copy()
    late = out["start_time_utc"] >= t0
    out.loc[late, "xga"] = rng.uniform(0, 10, late.sum())
    out.loc[late, "ga"] = rng.integers(0, 8, late.sum())
    out.loc[late, "shots"] = rng.integers(0, 50, late.sum())
    if flags:  # reshuffle who started each later team-game
        for _, idx in out[late].groupby(["game_id", "team_id"]).groups.items():
            st = np.zeros(len(idx), dtype=bool)
            st[rng.integers(0, len(idx))] = True
            out.loc[idx, "starter"] = st
    return out


def test_projected_and_expected_ignore_g_and_later(data):
    cfg, games, ggx, base = data
    # games in the second season, so the starter model has a training season
    sample = games[games.season == SEASONS[1]].sample(3, random_state=0)
    cols = [c for c in base.columns if c.startswith(("projected_", "expected_"))]
    for k, g in enumerate(sample.itertuples()):
        s = goalie_features(_scramble(ggx, g.start_time_utc, k, flags=True), games, cfg)
        s = s.set_index(["game_id", "team_id"]).sort_index()
        for team in (g.home_team_id, g.away_team_id):
            pd.testing.assert_series_equal(base.loc[(g.game_id, team), cols], s.loc[(g.game_id, team), cols],
                                           check_names=False)


def test_actual_starter_rating_uses_only_earlier_games(data):
    cfg, games, ggx, base = data
    sample = games[games.season == SEASONS[1]].sample(3, random_state=1)
    cols = [c for c in base.columns if c.startswith("actual_goalie_gsax") or c == "actual_goalie_shots_career"]
    for k, g in enumerate(sample.itertuples()):
        s = goalie_features(_scramble(ggx, g.start_time_utc, k, flags=False), games, cfg)
        s = s.set_index(["game_id", "team_id"]).sort_index()
        for team in (g.home_team_id, g.away_team_id):
            pd.testing.assert_series_equal(base.loc[(g.game_id, team), cols], s.loc[(g.game_id, team), cols],
                                           check_names=False)
