"""Leakage guarantee: features for game G must not depend on G or anything that started later."""
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
import yaml

from nhlmodel.config import repo_path
from nhlmodel.features.asof import SCHEDULE_COLS, build_features

CFG = yaml.safe_load(open(repo_path("configs/features/base.yaml")))
STATS = [
    f"{s}_{side}"
    for s in ["goals", "sog", "fenwick", "corsi", "goals_5v5", "fenwick_5v5", "corsi_5v5", "pp_goals", "sh_goals",
              "penalties"]
    for side in ("for", "against")
]


def synthetic_league(seed=0, n_teams=6, games_per_season=40, seasons=(20202021, 20212022)):
    rng = np.random.default_rng(seed)
    rows, gid = [], 0
    tzs = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Toronto",
           "America/Edmonton"]
    for season in seasons:
        start = pd.Timestamp(f"{season // 10000}-10-01T23:00:00Z")
        for i in range(games_per_season):
            # shuffle teams into pairs each "day"; some days a team rests
            order = rng.permutation(n_teams)
            day = start + timedelta(days=2 * i + int(rng.integers(0, 2)))  # one round per team per day
            for j in range(0, n_teams - 1, 2):
                h, a = int(order[j]) + 1, int(order[j + 1]) + 1
                gid += 1
                t = day + timedelta(minutes=30 * j)
                rows.append({"game_id": gid, "season": season, "start_time_utc": t, "local_date": (t - timedelta(hours=5)).date(),
                             "venue_timezone": tzs[h - 1], "neutral_site": False, "home_team_id": h, "away_team_id": a})
    games = pd.DataFrame(rows)
    sides = pd.concat([
        games.assign(team_id=games.home_team_id, opp_id=games.away_team_id, is_home=True),
        games.assign(team_id=games.away_team_id, opp_id=games.home_team_id, is_home=False),
    ])[["game_id", "season", "start_time_utc", "team_id", "opp_id", "is_home"]].reset_index(drop=True)
    for c in STATS:
        sides[c] = rng.integers(0, 60, len(sides))
    return games, sides


def scramble_from(tg, t0, seed):
    rng = np.random.default_rng(seed)
    tg = tg.copy()
    late = tg["start_time_utc"] >= t0
    for c in STATS:
        tg.loc[late, c] = rng.integers(0, 1000, late.sum())
    return tg


def assert_same_row(a: pd.Series, b: pd.Series):
    pd.testing.assert_series_equal(a, b, check_exact=False, rtol=1e-12, check_names=False)


@pytest.fixture(scope="module")
def league():
    games, tg = synthetic_league()
    return games, tg, build_features(games, tg, CFG).set_index("game_id")


def test_features_ignore_game_itself_and_all_later_games(league):
    games, tg, base = league
    for k, gid in enumerate(games["game_id"].sample(25, random_state=1)):
        t0 = games.loc[games.game_id == gid, "start_time_utc"].iloc[0]
        scrambled = build_features(games, scramble_from(tg, t0, seed=k), CFG).set_index("game_id")
        assert_same_row(base.loc[gid], scrambled.loc[gid])


def test_scrambling_the_past_does_change_features(league):
    """Guards against a vacuous pass: earlier games must actually influence features."""
    games, tg, base = league
    gid = int(games["game_id"].iloc[len(games) // 2])
    t0 = games.loc[games.game_id == gid, "start_time_utc"].iloc[0]
    past = tg.copy()
    early = past["start_time_utc"] < t0
    past.loc[early, "corsi_for"] = past.loc[early, "corsi_for"] + 500
    changed = build_features(games, past, CFG).set_index("game_id").loc[gid]
    assert not np.allclose(
        base.loc[gid, "home_l10_corsi_share"], changed["home_l10_corsi_share"], equal_nan=True
    )


def test_feature_builder_does_not_need_outcome_columns(league):
    games, tg, base = league
    assert {"home_score", "away_score", "home_win"}.isdisjoint(SCHEDULE_COLS)
    out = build_features(games[SCHEDULE_COLS], tg, CFG)
    assert len(out) == len(games)


def test_first_game_of_each_franchise_has_no_window_history(league):
    games, tg, base = league
    first = games.sort_values("start_time_utc").groupby("home_team_id").head(1)
    for gid in first.game_id:
        row = base.loc[gid]
        # home team's very first game in the data: nothing before it
        if games.loc[games.game_id == gid, "start_time_utc"].iloc[0] == games.loc[
            (games.home_team_id == row.home_team_id) | (games.away_team_id == row.home_team_id), "start_time_utc"
        ].min():
            assert np.isnan(row["home_l5_corsi_share"])


def test_same_team_simultaneous_games_are_rejected(league):
    games, tg, _ = league
    dup = tg.copy()
    first = dup.index[0]
    other = dup[(dup.team_id == dup.loc[first, "team_id"]) & (dup.index != first)].index[0]
    dup.loc[other, "start_time_utc"] = dup.loc[first, "start_time_utc"]
    with pytest.raises(ValueError, match="same start time"):
        build_features(games, dup, CFG)


def test_cross_season_off_resets_last_n_windows():
    games, tg = synthetic_league(seed=3)
    cfg = {**CFG, "windows": {**CFG["windows"], "cross_season": False, "ewm_halflife_games": []}}
    f = build_features(games, tg, cfg).set_index("game_id")
    second = games[games.season == 20212022].sort_values("start_time_utc")
    team = int(second.iloc[0].home_team_id)
    first_gid = second[(second.home_team_id == team) | (second.away_team_id == team)].iloc[0].game_id
    side = "home" if games.set_index("game_id").loc[first_gid, "home_team_id"] == team else "away"
    assert np.isnan(f.loc[first_gid, f"{side}_l5_corsi_share"])


def test_real_data_truncation_if_available():
    """Same guarantee on real processed data for one season, if it has been built."""
    p = repo_path("data/processed/events/20252026.parquet")
    if not p.exists():
        pytest.skip("processed data not present")
    from nhlmodel.features.team_games import build_team_games

    games = pd.read_parquet(repo_path("data/processed/games.parquet"))
    games = games[games.season == 20252026]
    tg = build_team_games(pd.read_parquet(p), games)
    base = build_features(games, tg, CFG).set_index("game_id")
    for k, gid in enumerate(games["game_id"].sample(5, random_state=2)):
        t0 = games.loc[games.game_id == gid, "start_time_utc"].iloc[0]
        cut = build_features(games, scramble_from(tg, t0, seed=k), CFG).set_index("game_id")
        assert_same_row(base.loc[gid], cut.loc[gid])
