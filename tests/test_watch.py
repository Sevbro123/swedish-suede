"""The lineup watcher's polling plan."""
import pandas as pd

from nhlmodel.watch import plan

T0 = pd.Timestamp("2026-10-20T22:00Z")


def _up(minutes_to_start):
    return pd.DataFrame({"game_id": range(1, len(minutes_to_start) + 1),
                         "start_time_utc": pd.to_datetime([T0 + pd.Timedelta(minutes=m) for m in minutes_to_start], utc=True)})


def test_polls_games_inside_the_window_every_minute():
    poll, wake = plan(_up([10, 24, 60]), T0, horizon_h=4, window_min=25)
    assert poll == [1, 2] and wake == T0 + pd.Timedelta(minutes=1)


def test_started_games_are_not_polled():
    poll, wake = plan(_up([-5, 0, 20]), T0, horizon_h=4, window_min=25)   # in progress, just started, due
    assert poll == [3]


def test_sleeps_until_the_next_game_enters_the_window_but_at_most_10_min():
    assert plan(_up([30]), T0, horizon_h=4, window_min=25) == ([], T0 + pd.Timedelta(minutes=5))
    assert plan(_up([120]), T0, horizon_h=4, window_min=25) == ([], T0 + pd.Timedelta(minutes=10))


def test_stops_when_nothing_starts_within_the_horizon():
    assert plan(_up([5 * 60]), T0, horizon_h=4, window_min=25) == ([], None)
    assert plan(_up([-30]), T0, horizon_h=4, window_min=25) == ([], None)   # only a game in progress
    assert plan(_up([]), T0, horizon_h=4, window_min=25) == ([], None)
