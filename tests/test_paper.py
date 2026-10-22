import numpy as np
import pandas as pd
import pytest

from nhlmodel.odds.partner import ODDS_COLS, append_log, parse, to_american
from nhlmodel.paper import build_bets, summary

CFG = {"bankroll": 100, "stake": 1, "min_edge": 0.03, "devig": "multiplicative", "max_price_age_min": 30}
T = pd.Timestamp("2026-10-22T23:00:00Z")


def _team(abbrev, ml):
    return {"abbrev": abbrev, "odds": [{"description": "MONEY_LINE_3_WAY", "value": "+300"},
                                       {"description": "MONEY_LINE_2_WAY", "value": ml}]}


def test_parse_partner_response():
    data = {"lastUpdatedUTC": "2026-10-22T22:00:00Z", "bettingPartner": {"name": "Book"},
            "games": [{"gameId": 1, "homeTeam": _team("BOS", "-150"), "awayTeam": _team("TOR", "+130")},
                      {"gameId": 2, "homeTeam": _team("NYR", "-110"), "awayTeam": {"abbrev": "NJD", "odds": []}},
                      {"gameId": 3, "homeTeam": _team("EDM", -500), "awayTeam": _team("CGY", 900)}]}  # 2: one side; 3: too wide
    df = parse(data)
    assert df["game_id"].tolist() == [1]
    assert df.iloc[0][["home_ml", "away_ml", "book"]].tolist() == [-150, 130, "Book"]


def test_to_american_reads_decimal_prices():
    assert to_american("2.50") == 150 and to_american(1.5) == -200 and to_american("-120") == -120
    assert to_american(None) is None and to_american("x") is None


def test_append_log_skips_unchanged_prices():
    row = lambda t, h, a: {"game_id": 1, "observed_at": t, "home_ml": h, "away_ml": a, "book": "B",
                           "odds_updated_utc": "", "source": "s"}
    log = pd.DataFrame([row("t1", -150, 130)], columns=ODDS_COLS)
    log = append_log(log, pd.DataFrame([row("t2", -150, 130)]))
    assert len(log) == 1
    log = append_log(log, pd.DataFrame([row("t3", -160, 140)]))
    assert log["observed_at"].tolist() == ["t1", "t3"]


def _odds(rows):
    return pd.DataFrame([{"game_id": g, "observed_at": t.isoformat(), "home_ml": h, "away_ml": a, "book": "B",
                          "odds_updated_utc": "", "source": "s"} for g, t, h, a in rows])


def _games(home_win):
    return pd.DataFrame({"game_id": [1, 2, 3], "start_time_utc": [T] * 3, "away_abbrev": ["TOR", "MTL", "OTT"],
                         "home_abbrev": ["BOS", "NYR", "FLA"], "home_win": home_win})


def test_bets_use_the_same_runs_price_and_settle():
    made = T - pd.Timedelta(minutes=10)
    log = pd.DataFrame({"game_id": [1, 2, 3], "made_at": [made.isoformat()] * 3, "p_home": [0.70, 0.30, 0.52],
                        "lineup": ["confirmed"] * 3})
    odds = _odds([(1, made - pd.Timedelta(hours=2), -110, -110),   # older price: not the bet price
                  (1, made, -150, 130),                            # bet price: no-vig home ~0.584
                  (1, T - pd.Timedelta(minutes=1), -170, 150),     # close: moved our way
                  (2, made, -110, -110),                           # away edge 0.20
                  (3, made, -110, -110)])                          # edge 0.02: pass
    bets = build_bets(log, odds, _games([1.0, 1.0, np.nan]), CFG, T + pd.Timedelta(hours=4)).set_index("game_id")
    assert bets.loc[1, "side"] == "home" and bets.loc[1, "price"] == -150
    assert bets.loc[1, "status"] == "won" and bets.loc[1, "profit"] == pytest.approx(100 / 150)
    assert bets.loc[1, "clv"] > 0 and bets.loc[1, "close_home_ml"] == -170
    assert bets.loc[2, "side"] == "away" and bets.loc[2, "status"] == "lost" and bets.loc[2, "profit"] == -1
    assert bets.loc[3, "side"] == "" and bets.loc[3, "status"] == "pass"
    s = summary(bets.reset_index(), CFG)
    assert (s["bets"], s["won"], s["lost"]) == (2, 1, 1)
    assert s["profit"] == pytest.approx(100 / 150 - 1, abs=0.01) and len(s["curve"]) == 2


def test_no_bet_without_a_fresh_price_or_after_puck_drop():
    made = T - pd.Timedelta(minutes=10)
    log = pd.DataFrame({"game_id": [1, 2], "made_at": [made.isoformat()] * 2, "p_home": [0.9, 0.9], "lineup": ["x"] * 2})
    odds = _odds([(1, made - pd.Timedelta(hours=1), -110, -110),   # stale
                  (2, made + pd.Timedelta(minutes=5), -110, -110)])  # read after the prediction
    assert build_bets(log, odds, _games([1.0, 1.0, 1.0]), CFG, T).empty


def test_open_bet_before_the_game():
    made = T - pd.Timedelta(minutes=10)
    log = pd.DataFrame({"game_id": [1], "made_at": [made.isoformat()], "p_home": [0.8], "lineup": ["x"]})
    bets = build_bets(log, _odds([(1, made, -110, -110)]), _games([np.nan] * 3), CFG, made)
    assert bets.loc[0, "status"] == "open" and np.isnan(bets.loc[0, "profit"])
