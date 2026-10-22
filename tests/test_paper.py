import numpy as np
import pandas as pd
import pytest

from nhlmodel.odds.partner import ODDS_COLS, append_log, parse, to_american
from nhlmodel.paper import LEG_COLS, build_bets, grade_parlays, stake_for, summary, update_parlays

CFG = {"bankroll": 100, "min_edge": 0.03, "devig": "multiplicative", "max_price_age_min": 30,
       "stake_tiers": [[0.03, 1], [0.05, 2], [0.08, 3]], "flat_stake": 1,
       "parlay": {"min_edge": 0.05, "max_legs": 3, "stake": 0.5}}
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
    return pd.DataFrame({"game_id": [1, 2, 3], "start_time_utc": [T] * 3, "local_date": [T.date()] * 3,
                         "away_abbrev": ["TOR", "MTL", "OTT"],
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
    # edge ~0.116 -> 3 units; the flat benchmark bets 1
    assert bets.loc[1, "stake"] == 3 and bets.loc[1, "status"] == "won"
    assert bets.loc[1, "profit"] == pytest.approx(3 * 100 / 150) and bets.loc[1, "profit_flat"] == pytest.approx(100 / 150)
    assert bets.loc[1, "clv"] > 0 and bets.loc[1, "close_home_ml"] == -170
    assert bets.loc[2, "side"] == "away" and bets.loc[2, "status"] == "lost" and bets.loc[2, "profit"] == -3
    assert bets.loc[3, "side"] == "" and bets.loc[3, "status"] == "pass" and bets.loc[3, "stake"] == 0
    s = summary(bets.reset_index(), grade_parlays(pd.DataFrame(columns=LEG_COLS), _games([1.0] * 3), T), CFG)
    assert (s["bets"], s["won"], s["lost"]) == (2, 1, 1)
    assert s["profit"] == pytest.approx(3 * (100 / 150 - 1), abs=0.01)
    assert s["flat"]["profit"] == pytest.approx(100 / 150 - 1, abs=0.01) and len(s["curve"]) == len(s["curve_flat"]) == 2


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


def test_stake_tiers():
    assert stake_for([0.02, 0.03, 0.049, 0.05, 0.079, 0.08, 0.2], CFG["stake_tiers"]).tolist() == [0, 1, 1, 2, 2, 3, 3]


def _open_bets(edges, date="2026-10-22", start=T):
    n = len(edges)
    return pd.DataFrame({"game_id": range(1, n + 1), "date": date, "start_utc": [start.isoformat()] * n,
                         "away": [f"A{i}" for i in range(n)], "home": [f"H{i}" for i in range(n)], "side": "home",
                         "price": 110, "p_home": 0.5, "p_mkt_home": 0.45, "made_at": "m", "edge": edges, "status": "open"})


def test_parlay_picks_strongest_and_locks_once_a_leg_starts():
    empty = pd.DataFrame(columns=LEG_COLS)
    legs = update_parlays(empty, _open_bets([0.04, 0.06, 0.09, 0.07, 0.051]), CFG, T - pd.Timedelta(hours=1))
    assert sorted(legs["game_id"]) == [2, 3, 4]               # top 3 of the 4 that clear 0.05
    assert update_parlays(empty, _open_bets([0.06, 0.04]), CFG, T - pd.Timedelta(hours=1)).empty   # one strong pick only
    # before any leg starts the parlay is re-picked; after, it stays as it was
    assert update_parlays(legs, _open_bets([0.06, 0.04]), CFG, T - pd.Timedelta(minutes=5)).empty
    locked = update_parlays(legs, _open_bets([0.06, 0.04]).assign(date="x"), CFG, T + pd.Timedelta(minutes=5))
    assert sorted(locked["game_id"]) == [2, 3, 4]


def test_grade_parlay():
    legs = pd.DataFrame({"date": "d", "game_id": [1, 2], "start_utc": [T.isoformat()] * 2, "away": ["A", "B"],
                         "home": ["H", "I"], "side": ["home", "away"], "price": [100, 150], "p": [0.6, 0.5],
                         "p_mkt": [0.5, 0.4], "made_at": "m", "stake": 0.5})
    won = grade_parlays(legs, pd.DataFrame({"game_id": [1, 2], "home_win": [1, 0]}), T).iloc[0]
    assert won["status"] == "won" and won["profit"] == pytest.approx(0.5 * (2.0 * 2.5 - 1)) and won["p"] == pytest.approx(0.3)
    lost = grade_parlays(legs, pd.DataFrame({"game_id": [1, 2], "home_win": [0, np.nan]}), T).iloc[0]
    assert lost["status"] == "lost" and lost["profit"] == -0.5
    wait = grade_parlays(legs, pd.DataFrame({"game_id": [1, 2], "home_win": [1, np.nan]}), T).iloc[0]
    assert wait["status"] == "pending" and np.isnan(wait["profit"])
