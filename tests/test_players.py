"""Player on-ice metrics and lineup features (features/players.py)."""
import pandas as pd
import pytest

from nhlmodel.features.players import _lookup, lineup_features, player_games, player_states

CFG = {"halflife_games": 40, "pseudo_xg": 10, "toi_halflife_games": 10, "default_toi_s": 600,
       "regular_window": 10, "regular_min": 5}


def _one_game():
    """Period 1 only: 5v5 until 600 s, then home power play until 720 s, then 5v5 to 1200 s."""
    ev = pd.DataFrame({
        "game_id": 1, "sort_order": range(6), "period": 1, "period_type": "REG",
        "t_period_s": [0, 300, 600, 650, 720, 1000],
        "type": ["faceoff", "shot-on-goal", "penalty", "shot-on-goal", "faceoff", "goal"],
        "situation_code": ["1551", "1551", "1451", "1451", "1551", "1551"],
        "event_team_id": [10, 10, 20, 10, 10, 20], "event_id": range(6),
    })
    xg = pd.DataFrame({"game_id": 1, "event_id": [1, 3, 5], "xg": [0.1, 0.5, 0.3]})
    # player 1 (home) is on 0-300 and 300-1200: the shot at 300 belongs to the shift ending at 300
    shifts = pd.DataFrame({
        "game_id": 1, "period": 1,
        "player_id": [1, 1, 2, 3, 9],
        "team_id": [10, 10, 10, 20, 20],
        "start_s": [0, 300, 300, 0, 0],
        "end_s": [300, 1200, 1200, 1200, 1200],
    })
    rosters = pd.DataFrame({"game_id": 1, "team_id": [10, 10, 20, 20], "player_id": [1, 2, 3, 9],
                            "position": ["C", "D", "C", "G"]})
    return ev, shifts, xg, rosters


def test_player_games_toi_and_on_ice_xg():
    pg = player_games(*_one_game()).set_index("player_id")
    assert 9 not in pg.index  # goalies are not skaters
    assert pg.loc[1, "toi5"] == 1200 - 120 and pg.loc[2, "toi5"] == 900 - 120
    # the 5v4 shot (0.5) never counts; the 300 s shot goes to player 1, not to player 2 who came on then
    assert pg.loc[1, "on_xgf"] == pytest.approx(0.1) and pg.loc[2, "on_xgf"] == 0
    assert pg.loc[1, "on_xga"] == pytest.approx(0.3) and pg.loc[3, "on_xgf"] == pytest.approx(0.3)
    assert pg.loc[2, "off_xgf"] == pytest.approx(0.1)


def test_lookup_is_strictly_before():
    t = pd.Timestamp("2020-01-01T00:00Z")
    states = pd.DataFrame({"player_id": [1, 1], "game_id": [1, 2], "start_time_utc": [t, t + pd.Timedelta("1D")],
                           "exp_toi": [100.0, 200.0]})
    q = pd.DataFrame({"player_id": [1, 1, 1], "start_time_utc": [t, t + pd.Timedelta("1D"), t + pd.Timedelta("2D")]})
    assert _lookup(q, states)["exp_toi"].tolist()[1:] == [100.0, 200.0]
    assert pd.isna(_lookup(q, states)["exp_toi"].iloc[0])


def _season(n_games=12):
    """Team 1 dresses players 1-3 every game except player 3 sits game 8; team 2 dresses 4-6."""
    t = pd.Timestamp("2020-10-01T23:00Z")
    games = pd.DataFrame({"game_id": range(1, n_games + 1),
                          "start_time_utc": [t + pd.Timedelta(days=i) for i in range(n_games)],
                          "home_team_id": 1, "away_team_id": 2})
    ro = []
    for g in games["game_id"]:
        ro += [{"game_id": g, "team_id": 1, "player_id": p, "position": "C"} for p in (1, 2, 3) if not (g == 8 and p == 3)]
        ro += [{"game_id": g, "team_id": 2, "player_id": p, "position": "C"} for p in (4, 5, 6)]
    rosters = pd.DataFrame(ro)
    pg = rosters.assign(toi5=600.0, on_xgf=1.0, on_xga=0.5, off_xgf=1.0, off_xga=1.0)
    pg.loc[pg["player_id"] == 3, "on_xgf"] = 3.0
    return games, rosters, pg


def test_lineup_projection_and_missing_regulars():
    games, rosters, pg = _season()
    lf = lineup_features(rosters, games, player_states(pg, games, CFG), CFG, {}).set_index(["game_id", "team_id"])
    # game 8: player 3 sits; actual lineup is missing a third of the regulars' TOI, projection is not
    assert lf.loc[(8, 1), "leaky_lineup_missing_toi_share"] == pytest.approx(1 / 3)
    assert lf.loc[(8, 1), "lineup_missing_toi_share"] == 0
    # game 9 projects from game 8, so the projection now misses player 3 and loses his strong share
    assert lf.loc[(9, 1), "lineup_missing_toi_share"] == pytest.approx(1 / 3)
    assert lf.loc[(9, 1), "lineup_on_xg_share"] < lf.loc[(10, 1), "lineup_on_xg_share"]
    # no history yet: neutral values
    assert lf.loc[(1, 1), "leaky_lineup_on_xg_share"] == pytest.approx(0.5)
