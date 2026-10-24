"""Elo results rating (features/elo.py): correct arithmetic and the as-of rule."""
import numpy as np
import pandas as pd

from nhlmodel.features.elo import elo_ratings

CFG = {"k": 6, "hfa": 35, "carry": 0.7}


def _games(n=12, seed=0, season=20212022):
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp("2021-10-01T23:00:00Z")
    return pd.DataFrame([{"game_id": i + 1, "season": season, "start_time_utc": t0 + pd.Timedelta(days=i),
                          "home_team_id": 1 + (i % 2), "away_team_id": 2 - (i % 2), "neutral_site": False,
                          "home_score": int(rng.integers(0, 6)), "away_score": int(rng.integers(0, 6))}
                         for i in range(n)])


def test_first_game_update():
    g = _games(2)
    g.loc[0, ["home_score", "away_score"]] = [3, 1]
    r = elo_ratings(g, CFG, {}).set_index(["game_id", "team_id"])["elo_rating"]
    assert r[(1, 1)] == r[(1, 2)] == 1500
    move = 6 * np.log(3) * (1 - 1 / (1 + 10 ** (-35 / 400)))
    assert np.isclose(r[(2, 1)], 1500 + move) and np.isclose(r[(2, 2)], 1500 - move)


def test_season_carryover_and_unplayed_games():
    g = _games(3)
    g.loc[0, ["home_score", "away_score"]] = [5, 0]
    g.loc[1, "season"] = g.loc[2, "season"] = 20222023
    g.loc[2, ["home_score", "away_score"]] = [np.nan, np.nan]
    g["home_score"] = g["home_score"].astype("Float64")
    g["away_score"] = g["away_score"].astype("Float64")
    r = elo_ratings(g, CFG, {}).set_index(["game_id", "team_id"])["elo_rating"]
    after1 = 1500 + 6 * np.log(6) * (1 - 1 / (1 + 10 ** (-35 / 400)))
    assert np.isclose(r[(2, 1)], 1500 + 0.7 * (after1 - 1500))
    assert np.isfinite(r[(3, 1)])


def test_uses_only_earlier_games():
    g = _games(seed=1)
    base = elo_ratings(g, CFG, {}).set_index(["game_id", "team_id"]).sort_index()
    for k in (4, 8):
        s = g.copy()
        s.loc[s["game_id"] >= k, ["home_score", "away_score"]] = 9, 0
        f = elo_ratings(s, CFG, {}).set_index(["game_id", "team_id"]).sort_index()
        pd.testing.assert_frame_equal(base.loc[base.index.get_level_values(0) <= k],
                                      f.loc[f.index.get_level_values(0) <= k])
