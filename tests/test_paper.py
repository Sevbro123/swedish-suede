import numpy as np
import pandas as pd
import pytest

from nhlmodel.odds.partner import ODDS_COLS, append_log, parse, to_american
from nhlmodel.paper import LEG_COLS, build_bets, grade_parlays, stake_for, summary, unit_size, update_parlays

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


def test_append_log_skips_unchanged_prices_but_refreshes_old_ones():
    row = lambda m, h, a: {"game_id": 1, "observed_at": (T + pd.Timedelta(minutes=m)).isoformat(), "home_ml": h,
                           "away_ml": a, "book": "B", "odds_updated_utc": "", "source": "s"}
    log = pd.DataFrame([row(0, -150, 130)], columns=ODDS_COLS)
    log = append_log(log, pd.DataFrame([row(1, -150, 130)]))      # unchanged, fresh: skipped
    assert len(log) == 1
    log = append_log(log, pd.DataFrame([row(2, -160, 140)]))      # changed: kept
    log = append_log(log, pd.DataFrame([row(40, -160, 140)]))     # unchanged but last row 38 min old: kept
    assert [pd.Timestamp(t) - T for t in log["observed_at"]] == [pd.Timedelta(minutes=m) for m in (0, 2, 40)]


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
    # open -110/-110 (0.5) -> close -170/150: the line moved toward our home pick from the first price too
    assert bets.loc[1, "open_home_ml"] == -110 and bets.loc[1, "open_clv"] > bets.loc[1, "clv"]
    # games 2 and 3 have one price only: bet, open and close are the same read, so nothing is measured
    assert np.isnan(bets.loc[2, "clv"]) and np.isnan(bets.loc[2, "open_clv"])
    assert bets.loc[2, "side"] == "away" and bets.loc[2, "status"] == "lost" and bets.loc[2, "profit"] == -3
    assert bets.loc[3, "side"] == "" and bets.loc[3, "status"] == "pass" and bets.loc[3, "stake"] == 0
    s = summary(bets.reset_index(), grade_parlays(pd.DataFrame(columns=LEG_COLS), _games([1.0] * 3), T), CFG)
    assert (s["bets"], s["won"], s["lost"]) == (2, 1, 1)
    assert s["profit"] == pytest.approx(3 * (100 / 150 - 1), abs=0.01)
    assert s["flat"]["profit"] == pytest.approx(100 / 150 - 1, abs=0.01) and len(s["curve"]) == len(s["curve_flat"]) == 2


def test_clv_blank_when_bet_and_close_share_a_feed_snapshot():
    made = T - pd.Timedelta(minutes=10)
    log = pd.DataFrame({"game_id": [1], "made_at": [made.isoformat()], "p_home": [0.8], "lineup": ["x"]})
    odds = _odds([(1, made - pd.Timedelta(hours=3), -120, 100), (1, made, -110, -110), (1, T - pd.Timedelta(minutes=1), -110, -110)])
    odds["odds_updated_utc"] = ["2026-10-22T19:30:38Z", "2026-10-22T22:30:38Z", "2026-10-22T22:30:38Z"]   # re-read of one snapshot
    b = build_bets(log, odds, _games([1.0] * 3), CFG, T + pd.Timedelta(hours=4)).iloc[0]
    assert np.isnan(b["clv"]) and b["open_home_ml"] == -120 and b["open_clv"] < 0   # line drifted away from home
    s = summary(build_bets(log, odds, _games([1.0] * 3), CFG, T + pd.Timedelta(hours=4)), pd.DataFrame(columns=["status"]), CFG)
    assert s["clv_n"] == 0 and s["avg_clv"] is None and s["open_clv_n"] == 1 and s["beat_open"] == 0


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


SIZED = {**CFG, "goal": 10000, "sizing": {"unit_pct": 0.01, "step": 0.25, "min_unit": 1, "max_bet_pct": 0.04}}


def test_unit_size_grows_with_bankroll_and_never_drops_below_one():
    assert unit_size(100, CFG) == 1
    assert [unit_size(b, SIZED) for b in (50, 100, 124.9, 125, 260, 10000)] == [1, 1, 1, 1.25, 2.5, 100]


def test_stakes_size_from_the_previous_days_bankroll():
    t1, t2 = T, T + pd.Timedelta(days=1)
    log = pd.DataFrame({"game_id": [1, 2], "made_at": [(t1 - pd.Timedelta(minutes=10)).isoformat(),
                                                       (t2 - pd.Timedelta(minutes=10)).isoformat()],
                        "p_home": [0.95, 0.95], "lineup": ["x"] * 2})
    odds = _odds([(1, t1 - pd.Timedelta(minutes=10), 2000, -5000), (2, t2 - pd.Timedelta(minutes=10), -110, -110)])
    games = pd.DataFrame({"game_id": [1, 2], "start_time_utc": [t1, t2], "local_date": [t1.date(), t2.date()],
                          "away_abbrev": ["A", "B"], "home_abbrev": ["H", "I"], "home_win": [1.0, 1.0]})
    bets = build_bets(log, odds, games, SIZED, t2 + pd.Timedelta(hours=4)).set_index("game_id")
    # day 1: 3u at +2000 wins 60u -> day 2 starts at 160u, so one unit is 1.5u and the 3-unit bet stakes 4.5u
    assert bets.loc[1, "stake"] == 3 and bets.loc[1, "profit"] == pytest.approx(60)
    assert bets.loc[2, "unit"] == 1.5 and bets.loc[2, "stake"] == 4.5
    assert bets.loc[2, "profit_flat"] == pytest.approx(100 / 110)   # benchmark stays 1u
    # a parlay that lost 20u on day 1 counts too: 140u -> 1.25u units
    lost = pd.DataFrame({"date": [str(t1.date())], "status": ["lost"], "profit": [-20.0]})
    assert build_bets(log, odds, games, SIZED, t2, lost).set_index("game_id").loc[2, "unit"] == 1.25
    s = summary(bets.reset_index(), grade_parlays(pd.DataFrame(columns=LEG_COLS), games, T), SIZED)
    assert s["unit"] == unit_size(s["bankroll"], SIZED) and s["doublings_needed"] == pytest.approx(6.644, abs=1e-3)


def test_bet_cap_after_a_drawdown():
    made = T - pd.Timedelta(minutes=10)
    log = pd.DataFrame({"game_id": [1], "made_at": [made.isoformat()], "p_home": [0.9], "lineup": ["x"]})
    cfg = {**SIZED, "bankroll": 50}
    bets = build_bets(log, _odds([(1, made, -110, -110)]), _games([np.nan] * 3), cfg, made)
    assert bets.loc[0, "stake"] == 2   # 3 units, capped at 4% of 50u


def test_parlay_stake_scales_with_unit():
    legs = update_parlays(pd.DataFrame(columns=LEG_COLS), _open_bets([0.06, 0.07]).assign(unit=2.0), CFG, T - pd.Timedelta(hours=1))
    assert (legs["stake"] == 1.0).all()
