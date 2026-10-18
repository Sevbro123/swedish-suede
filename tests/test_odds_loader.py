from datetime import date

import pandas as pd
import pytest

from nhlmodel.odds.loader import OddsValidationError, match_to_games, validate_odds


def odds_frame(**over):
    row = {
        "game_date": "2023-11-10",
        "home_team": "Buffalo",
        "away_team": "Minnesota",
        "home_ml": -130,
        "away_ml": 110,
        "snapshot_ts": None,
        "book": "consensus",
        "line_type": "close",
        "source": "test",
    }
    row.update(over)
    return pd.DataFrame([row])


def test_valid_frame_gets_overround():
    df = validate_odds(odds_frame())
    assert df.loc[0, "overround"] == pytest.approx(130 / 230 + 100 / 210 - 1)
    assert df.loc[0, "game_date"] == date(2023, 11, 10)


def test_missing_column_rejected():
    with pytest.raises(OddsValidationError, match="missing columns"):
        validate_odds(odds_frame().drop(columns=["book"]))


def test_bad_line_type_rejected():
    with pytest.raises(OddsValidationError, match="line_type"):
        validate_odds(odds_frame(line_type="closing"))


def test_implausible_overround_rejected():
    # +200/+200 has a negative overround: an arbitrage, which signals a data error.
    with pytest.raises(OddsValidationError, match="overround"):
        validate_odds(odds_frame(home_ml=200, away_ml=200))


def test_match_reports_unmatched_rows_instead_of_dropping():
    odds = validate_odds(pd.concat([odds_frame(), odds_frame(home_team="Nowhere")], ignore_index=True))
    games = pd.DataFrame(
        [{"game_id": 2023020204, "local_date": date(2023, 11, 10), "home_team_id": 7, "away_team_id": 30}]
    )
    matched, unmatched = match_to_games(odds, games, {"Buffalo": 7, "Minnesota": 30})
    assert matched["game_id"].tolist() == [2023020204]
    assert len(unmatched) == 1 and unmatched.loc[0, "home_team"] == "Nowhere"
