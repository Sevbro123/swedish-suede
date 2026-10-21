"""5v5 stints and RAPM ratings (ratings/stints.py, ratings/rapm.py) and the lineup RAPM features."""
import numpy as np
import pandas as pd
import pytest

from nhlmodel.features.players import rapm_lineup_features
from nhlmodel.ratings.rapm import fit_monthly, month_of, monthly_equations, player_ratings
from nhlmodel.ratings.stints import AWAY, HOME, build_stints, validate

H_SK, A_SK = [1, 2, 3, 4, 5], [11, 12, 13, 14, 15]


def _game():
    """Period 1 only. Home skater 1 is replaced by 6 at 300 s; the away goalie is pulled from 1100 s
    (the 6-on-5 shot at 1100 s is coded 1560 and belongs to no stint)."""
    shifts = [(p, 10, 0, 300) for p in [1]] + [(6, 10, 300, 1200)] + [(p, 10, 0, 1200) for p in H_SK[1:]]
    shifts += [(p, 20, 0, 1200) for p in A_SK] + [(99, 10, 0, 1200), (98, 20, 0, 1100), (16, 20, 1100, 1200)]
    sh = pd.DataFrame(shifts, columns=["player_id", "team_id", "start_s", "end_s"]).assign(game_id=1, period=1)
    ev = pd.DataFrame({
        "game_id": 1, "sort_order": range(5), "event_id": range(5), "period": 1, "period_type": "REG",
        "t_period_s": [0, 300, 500, 1000, 1100],
        "type": ["faceoff", "shot-on-goal", "goal", "missed-shot", "shot-on-goal"],
        "situation_code": ["1551", "1551", "1551", "1551", "1560"],
        "event_team_id": [10, 10, 20, 10, 10], "home_team_id": 10,
    })
    xg = pd.DataFrame({"game_id": 1, "event_id": [1, 2, 3, 4], "xg": [0.1, 0.3, 0.2, 0.4]})
    ro = pd.DataFrame({"game_id": 1, "team_id": [10] * 7 + [20] * 7,
                       "player_id": H_SK + [6, 99] + A_SK + [16, 98], "position": ["C"] * 6 + ["G"] + ["C"] * 6 + ["G"]})
    return ev, sh, xg, ro


def test_stints_split_on_changes_and_drop_pulled_goalie():
    st, chk = build_stints(*_game())
    assert st[["start_s", "end_s"]].values.tolist() == [[0, 300], [300, 1100]]
    assert st.loc[0, HOME].tolist() == [1, 2, 3, 4, 5] and st.loc[1, HOME].tolist() == [2, 3, 4, 5, 6]
    assert st.loc[0, AWAY].tolist() == A_SK
    # the shot at 300 s goes to the stint ending then; the goal at 500 s makes the home team trail after it
    assert st["xg_home"].tolist() == pytest.approx([0.1, 0.2]) and st["xg_away"].tolist() == pytest.approx([0, 0.3])
    assert st["home_lead"].tolist() == [0, 0]
    assert chk.loc[0, "xg_5v5"] == pytest.approx(0.6) and chk.loc[0, "xg_stints"] == pytest.approx(0.6)
    assert validate(chk)["ok"].all()


def _synthetic(n_games=60, seed=0):
    """Random 5v5 stints from two pools of ten skaters; player 1 adds 0.5 xG/60, player 21 prevents 0.5."""
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp("2020-10-01T23:00Z")
    games = pd.DataFrame({"game_id": range(n_games), "start_time_utc": [t0 + pd.Timedelta(days=3 * i) for i in range(n_games)]})
    rows = []
    for g in games["game_id"]:
        for k in range(60):
            h = np.sort(rng.choice(np.arange(1, 11), 5, replace=False))
            a = np.sort(rng.choice(np.arange(21, 31), 5, replace=False))
            rate_h = 2.5 + 0.5 * (1 in h) - 0.5 * (21 in a)
            rate_a = 2.5
            rows.append([g, *h, *a, 60 * k, 60 * (k + 1), 60, 0, rate_h / 60 + rng.normal(0, 0.005), rate_a / 60])
    st = pd.DataFrame(rows, columns=["game_id"] + HOME + AWAY + ["start_s", "end_s", "dur_s", "home_lead", "xg_home", "xg_away"])
    return st, games


def test_rapm_recovers_offense_and_defense():
    st, games = _synthetic()
    r = player_ratings(st, games, {"lam": 1.0, "halflife_months": None})
    last = r[r["month"] == r["month"].max()].set_index("player_id")
    # each pool always fields five of its ten players, so ratings are identified relative to the pool
    home, away = last.loc[1:10], last.loc[21:30]
    assert last.loc[1, "off"] - home["off"].drop(1).mean() == pytest.approx(0.5, abs=0.05)
    assert last.loc[21, "def"] - away["def"].drop(21).mean() == pytest.approx(0.5, abs=0.05)
    assert home["off"].drop(1).std() < 0.05 and away["def"].drop(21).std() < 0.05


def test_ratings_for_a_month_use_only_earlier_games():
    st, games = _synthetic()
    cut = month_of(games["start_time_utc"]).unique()[2]
    r_full = player_ratings(st, games, {"lam": 50.0, "halflife_months": 12})
    early = games[month_of(games["start_time_utc"]) < cut]
    st_trunc = st[st["game_id"].isin(set(early["game_id"]))]
    idx, eqs = monthly_equations(st_trunc, games)
    r_trunc = fit_monthly(idx, eqs, [cut], 50.0, 12)
    a = r_full[r_full["month"] == cut].set_index("player_id")[["off", "def"]]
    b = r_trunc.set_index("player_id")[["off", "def"]]
    pd.testing.assert_frame_equal(a.sort_index(), b.sort_index(), atol=1e-10)


def test_rapm_lineup_features_weight_by_toi_and_month():
    t = pd.Timestamp("2021-01-15T00:00Z")
    sides = pd.DataFrame({"game_id": [1], "team_id": [10]})
    members = pd.DataFrame({"game_id": 1, "team_id": 10, "start_time_utc": t, "player_id": [1, 2, 3],
                            "proj": [True, True, False], "actual": [True, False, True], "exp_toi": [900.0, 300.0, 600.0]})
    ratings = pd.DataFrame({"month": [pd.Period("2021-01", "M"), pd.Period("2021-01", "M"), pd.Period("2021-02", "M")],
                            "player_id": [1, 3, 2], "off": [0.4, 0.2, 9.0], "def": [0.0, 0.1, 9.0]})
    f = rapm_lineup_features(sides, members, ratings).iloc[0]
    # player 2 has no January rating, so counts as average (0)
    assert f["rapm_off"] == pytest.approx(5 * 0.4 * 900 / 1200)
    assert f["leaky_rapm_off"] == pytest.approx(5 * (0.4 * 900 + 0.2 * 600) / 1500)
    assert f["leaky_rapm_net"] == pytest.approx(f["leaky_rapm_off"] + f["leaky_rapm_def"])
