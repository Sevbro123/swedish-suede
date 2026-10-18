import numpy as np
import pandas as pd
import pytest

from nhlmodel.xg.model import attack_sign, shot_features


def ev(**over):
    row = dict(game_id=2023020001, event_id=1, sort_order=1, period=1, period_type="REG", t_game_s=100,
               type="shot-on-goal", situation_code="1551", away_goalie_in=1, away_skaters=5, home_skaters=5,
               home_goalie_in=1, home_defending_side="left", event_team_id=7, is_home_event=True, x=80.0, y=5.0,
               zone_code="O", shot_type="wrist", goalie_id=99)
    row.update(over)
    return row


def test_attack_sign_from_defending_side_field():
    df = pd.DataFrame([ev(), ev(is_home_event=False, event_team_id=30), ev(home_defending_side="right")])
    assert attack_sign(df).tolist() == [1.0, -1.0, -1.0]


def test_attack_sign_fallback_uses_offensive_zone_majority():
    rows = [ev(home_defending_side=None, x=x, sort_order=i) for i, x in enumerate([-70, -60, -80, 50])]
    assert (attack_sign(pd.DataFrame(rows)) == -1.0).all()


def test_distance_and_angle_after_normalisation():
    # Home attacks -x (defends right): a shot at x=-80, y=0 is 9 ft straight out from the net.
    f = shot_features(pd.DataFrame([ev(home_defending_side="right", x=-80.0, y=0.0)]))
    assert f.loc[0, "distance"] == pytest.approx(9.0) and f.loc[0, "angle"] == pytest.approx(0.0)


def test_rebound_flag_and_score_state():
    rows = [
        ev(sort_order=1, t_game_s=50, type="goal", x=70.0),                                  # home leads 1-0
        ev(sort_order=2, t_game_s=100, type="shot-on-goal", x=60.0),
        ev(sort_order=3, t_game_s=102, type="missed-shot", x=85.0),                           # rebound
        ev(sort_order=4, t_game_s=110, type="shot-on-goal", event_team_id=30, is_home_event=False, x=-60.0),
    ]
    f = shot_features(pd.DataFrame(rows)).set_index("event_id", drop=False)
    f = f.reset_index(drop=True)
    assert f["rebound"].tolist() == [0, 0, 1, 0]
    assert f["score_diff"].tolist() == [0, 1, 1, -1]  # the away team trails 0-1 on its shot


def test_penalty_shots_and_blocked_shots_excluded():
    rows = [ev(situation_code="0101", away_skaters=0, home_skaters=1, away_goalie_in=1, home_goalie_in=0),
            ev(type="blocked-shot", sort_order=2)]
    assert len(shot_features(pd.DataFrame(rows))) == 0


def test_empty_net_shot_kept_and_flagged():
    f = shot_features(pd.DataFrame([ev(situation_code="0651", away_goalie_in=0, away_skaters=6)]))
    assert len(f) == 1 and f.loc[0, "empty_net"] == 1
