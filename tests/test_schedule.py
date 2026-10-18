from datetime import date

import pandas as pd
import pytest

from nhlmodel.ingest.schedule import _parse_game, finalize, local_date


def raw_game(gid, home_score, away_score, state="OFF", sched="OK", period="REG"):
    return {
        "id": gid,
        "season": 20232024,
        "gameType": 2,
        "startTimeUTC": "2023-11-11T00:00:00Z",
        "venueUTCOffset": "-05:00",
        "venueTimezone": "US/Eastern",
        "neutralSite": False,
        "homeTeam": {"id": 7, "abbrev": "BUF", "score": home_score},
        "awayTeam": {"id": 30, "abbrev": "MIN", "score": away_score},
        "gameOutcome": {"lastPeriodType": period},
        "gameState": state,
        "gameScheduleState": sched,
    }


def test_local_date_crosses_midnight_utc():
    assert local_date(pd.Timestamp("2023-11-11T00:00:00Z"), "-05:00") == date(2023, 11, 10)
    assert local_date(pd.Timestamp("2023-11-11T02:30:00Z"), "-08:00") == date(2023, 11, 10)
    assert local_date(pd.Timestamp("2023-11-11T18:00:00Z"), "+01:00") == date(2023, 11, 11)


def test_finalize_keeps_completed_and_sets_target_including_shootouts():
    df = pd.DataFrame(
        [
            _parse_game(raw_game(1, 3, 2)),
            _parse_game(raw_game(2, 2, 3, period="SO")),
            _parse_game(raw_game(3, None, None, state="FUT")),
            _parse_game(raw_game(4, 0, 0, state="OFF", sched="CNCL")),
        ]
    )
    out = finalize(df)
    assert out["game_id"].tolist() == [1, 2]
    assert out["home_win"].tolist() == [1, 0]
    assert out["decided_in"].tolist() == ["REG", "SO"]
    assert out["local_date"].tolist() == [date(2023, 11, 10)] * 2


def test_finalize_rejects_tied_completed_game():
    with pytest.raises(ValueError):
        finalize(pd.DataFrame([_parse_game(raw_game(1, 2, 2))]))
