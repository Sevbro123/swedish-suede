"""Recent-form features (features/form.py): correct arithmetic and the as-of rule."""
import numpy as np
import pandas as pd

from nhlmodel.features.form import _lookup, skater_states, team_form

CFG = {"windows": [2, 3], "baseline_halflife_games": 10, "baseline_pseudo_games": 5}


def _games(n=12, seed=0):
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp("2021-10-01T23:00:00Z")
    rows = [{"game_id": i + 1, "start_time_utc": t0 + pd.Timedelta(days=i), "home_team_id": 1 + (i % 2),
             "away_team_id": 2 - (i % 2), "home_win": int(rng.integers(0, 2))} for i in range(n)]
    return pd.DataFrame(rows)


def test_team_streak_and_win_rate():
    g = _games()
    g["home_team_id"], g["away_team_id"] = 1, 2
    g["home_win"] = [1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 1, 1]
    f = team_form(g, CFG, {}).set_index(["game_id", "team_id"])
    assert f.loc[(1, 1), "form_streak"] == 0
    assert f.loc[(4, 1), "form_streak"] == 3 and f.loc[(4, 2), "form_streak"] == -3
    assert f.loc[(6, 1), "form_streak"] == -2
    assert f.loc[(4, 1), "form_win_l2"] == 0.5  # won games 2 and 3
    assert f.loc[(6, 1), "form_win_l3"] == 1 / 3 - 0.5  # games 3-5: W L L


def test_team_form_uses_only_earlier_games():
    g = _games(seed=1)
    base = team_form(g, CFG, {}).set_index(["game_id", "team_id"]).sort_index()
    for k in (4, 8):
        s = g.copy()
        s.loc[s["game_id"] >= k, "home_win"] = 1 - s.loc[s["game_id"] >= k, "home_win"]
        f = team_form(s, CFG, {}).set_index(["game_id", "team_id"]).sort_index()
        pd.testing.assert_frame_equal(base.loc[base.index.get_level_values(0) <= k],
                                      f.loc[f.index.get_level_values(0) <= k])


def test_skater_form_uses_only_earlier_games_and_is_recent_minus_norm():
    g = _games()
    rng = np.random.default_rng(2)
    sg = pd.DataFrame({"game_id": g["game_id"], "team_id": 1, "player_id": 7, "pos": "F",
                       "pts": rng.integers(0, 3, len(g)).astype(float), "goals": 0.0, "ixg": 0.1})
    q = g[["game_id", "start_time_utc"]].assign(player_id=7)
    base = _lookup(q, skater_states(sg, g, CFG)).set_index("game_id")
    for k in (5, 9):
        s = sg.copy()
        s.loc[s["game_id"] >= k, "pts"] = 9.0
        f = _lookup(q, skater_states(s, g, CFG)).set_index("game_id")
        pd.testing.assert_frame_equal(base.loc[:k], f.loc[:k])
    # a constant stat equal to the league rate has no form (once a league rate exists: after game 1)
    assert np.allclose(base.loc[3:, "ixg_l2"], 0.0)
    # a big game raises recent form above the norm
    hot = sg.copy()
    hot.loc[hot["game_id"] == 6, "pts"] += 5
    f = _lookup(q, skater_states(hot, g, CFG)).set_index("game_id")
    assert f.loc[7, "pts_l2"] > base.loc[7, "pts_l2"]
