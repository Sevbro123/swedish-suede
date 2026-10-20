"""Current-season update and upcoming-game predictions."""
import numpy as np
import pandas as pd

from nhlmodel.features.goalies import starter_candidates
from nhlmodel.features.team_games import build_team_games
from nhlmodel.ingest.nhl import _key, latest_snapshot
from nhlmodel.ingest.schedule import upcoming
from nhlmodel.models.families import actual_lineup
from nhlmodel.predict import next_games

T0 = pd.Timestamp("2026-10-20T12:00Z")


def test_snapshot_keys_and_latest(tmp_path):
    assert _key("nhl_web/pbp/2026/1", None) == "nhl_web/pbp/2026/1"
    assert _key("nhl_web/pbp/2026/1", "20261020T1200Z") == "snap/20261020T1200Z/nhl_web/pbp/2026/1"
    for ts in ("20261019T0900Z", "20261020T1200Z", "20261020T0800Z"):
        p = tmp_path / "snap" / ts / "nhl_web/pbp/2026/1.json.gz"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"")
    assert latest_snapshot(tmp_path, "nhl_web/pbp/2026/1").parts[-5] == "20261020T1200Z"
    assert latest_snapshot(tmp_path, "nhl_web/pbp/2026/2") is None


def _sched(states, starts):
    n = len(states)
    return pd.DataFrame({
        "game_id": range(1, n + 1), "season": 20262027, "game_type": 2, "start_time_utc": starts,
        "venue_utc_offset": "-04:00", "venue_timezone": "America/New_York", "neutral_site": False,
        "home_team_id": [1, 3, 1, 2][:n], "home_abbrev": "H", "away_team_id": [2, 4, 3, 4][:n], "away_abbrev": "A",
        "home_score": None, "away_score": None, "last_period_type": None, "game_state": states, "schedule_state": "OK",
    })


def test_upcoming_keeps_unstarted_games_in_window_without_outcomes():
    starts = [T0 - pd.Timedelta(hours=5), T0 + pd.Timedelta(hours=8), T0 + pd.Timedelta(days=1), T0 + pd.Timedelta(days=5)]
    up = upcoming(_sched(["OFF", "FUT", "PRE", "FUT"], starts), T0, days=2)
    assert up["game_id"].tolist() == [2, 3]
    assert not {"home_score", "away_score", "last_period_type"} & set(up.columns)


def test_next_games_only_each_teams_next_game():
    starts = [T0 + pd.Timedelta(hours=h) for h in (1, 2, 30, 31)]
    up = _sched(["FUT"] * 4, starts)  # games: 1v2, 3v4, 1v3, 2v4
    assert next_games(up)["game_id"].tolist() == [1, 2]


def test_unplayed_games_have_no_stats_not_zeros():
    games = pd.DataFrame({"game_id": [1, 2], "season": 20262027, "start_time_utc": [T0, T0 + pd.Timedelta(days=1)],
                          "home_team_id": [1, 1], "away_team_id": [2, 2]})
    ev = pd.DataFrame({"game_id": [1, 1], "event_id": [1, 2], "sort_order": [1, 2], "period": 1, "period_type": "REG",
                       "t_game_s": [10, 20], "type": ["shot-on-goal", "goal"], "event_team_id": [1, 2],
                       "is_home_event": [True, False], "home_skaters": 5, "away_skaters": 5, "home_goalie_in": 1,
                       "away_goalie_in": 1, "pen_minutes": np.nan})
    tg = build_team_games(ev, games).set_index(["game_id", "team_id"])
    assert tg.loc[(1, 1), "sog_for"] == 1 and tg.loc[(1, 1), "goals_against"] == 1
    assert tg.loc[(2, 1), ["sog_for", "goals_against", "corsi_for"]].isna().all()


def test_goalie_candidates_for_the_unplayed_next_game():
    days = pd.date_range("2026-10-01", periods=6, freq="2D")
    games = pd.DataFrame({"game_id": range(1, 7), "season": 20262027, "start_time_utc": days.tz_localize("UTC"),
                          "local_date": days.date, "home_team_id": 1, "away_team_id": 2})
    gg = pd.DataFrame([{"game_id": g, "team_id": 1, "player_id": 30 if g % 2 else 31, "starter": True} for g in range(1, 6)])
    c = starter_candidates(gg, games)
    nxt = c[c["game_id"] == 6].set_index("player_id")
    assert set(nxt.index) == {30, 31} and nxt["label"].isna().all()
    assert nxt.loc[30, "started_prev"] == 1 and nxt.loc[31, "days_since_start"] == 4


def test_actual_lineup_copies_leaky_columns_into_lineup_columns():
    f = pd.DataFrame({"home_lineup_on_xg_share": [0.5], "home_leaky_lineup_on_xg_share": [0.55],
                      "away_lineup_rel_xg_share": [0.0], "away_leaky_lineup_rel_xg_share": [0.01]})
    a = actual_lineup(f)
    assert a.loc[0, "home_lineup_on_xg_share"] == 0.55 and a.loc[0, "away_lineup_rel_xg_share"] == 0.01
    assert f.loc[0, "home_lineup_on_xg_share"] == 0.5  # input untouched


def test_prune_snapshots_keeps_recent_folders(tmp_path):
    from nhlmodel.live import prune_snapshots

    for name in ("20261015T120000Z", "20261019T120000Z", "20261020T110000Z", "notatime"):
        (tmp_path / "snap" / name).mkdir(parents=True)
    assert prune_snapshots(tmp_path, 2, T0) == 1
    assert sorted(p.name for p in (tmp_path / "snap").iterdir()) == ["20261019T120000Z", "20261020T110000Z", "notatime"]


def test_predictions_log_keeps_the_latest_pregame_prediction():
    from nhlmodel.live import LOG_COLS, update_log

    log = pd.DataFrame([[1, "2026-10-19T14:00:00+00:00", 0.6, "projected"],
                        [2, "2026-10-19T14:00:00+00:00", 0.4, "projected"]], columns=LOG_COLS)
    preds = pd.DataFrame({"game_id": [2, 3], "p_home": [0.45, 0.55], "lineup": ["confirmed", "projected"]})
    out = update_log(log, preds, T0).set_index("game_id")
    assert list(out.index) == [1, 2, 3]
    assert out.loc[1, "p_home"] == 0.6                      # game already started: untouched
    assert out.loc[2, "p_home"] == 0.45 and out.loc[2, "lineup"] == "confirmed"
