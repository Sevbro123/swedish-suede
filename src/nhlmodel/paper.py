"""Paper trading: the bets the live model would have made at the NHL partner book's prices, graded.

Nothing is stored beyond the two logs the live runs already keep, so the bets are rebuilt from them each
run and the rules can't drift from what was known at the time:

- the bet: each game's last prediction before puck drop (predictions_log.csv), at the price read in the
  same run (the newest odds-log row at most ``max_price_age_min`` before the prediction). It bets the side
  whose model chance beats the book's no-vig chance by ``min_edge`` or more, ``stake`` units flat.
- the close: the newest price read before puck drop. Closing-line value (CLV) is the bet side's no-vig
  chance at the close minus at the bet: positive means the market moved toward us.
- settlement: 2-way moneyline, overtime and shootout included (games.parquet ``home_win``).

Writes paper_bets.csv: one row per game we had a price for, ``side`` empty when there was no bet.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .odds.vig import american_to_decimal, devig

BET_COLS = ["game_id", "start_utc", "away", "home", "made_at", "lineup", "p_home", "home_ml", "away_ml", "book",
            "p_mkt_home", "edge_home", "side", "price", "stake", "close_home_ml", "close_away_ml", "clv",
            "status", "profit"]


def _latest_before(odds: pd.DataFrame, cutoff: pd.Series) -> pd.DataFrame:
    """For each row of ``cutoff`` (indexed by game_id), the newest odds row observed strictly before it."""
    o = odds.merge(cutoff.rename("cutoff"), left_on="game_id", right_index=True)
    o = o[o["observed_at"] < o["cutoff"]]
    return o.sort_values("observed_at").groupby("game_id").tail(1).set_index("game_id")


def build_bets(log: pd.DataFrame, odds: pd.DataFrame, games: pd.DataFrame, cfg: dict, now: pd.Timestamp) -> pd.DataFrame:
    """``log``: predictions log (game_id, made_at, p_home, lineup). ``odds``: odds log. ``games``: game_id,
    start_time_utc, away_abbrev, home_abbrev and home_win (NaN until final), for every logged game."""
    if log.empty or odds.empty:
        return pd.DataFrame(columns=BET_COLS)
    odds = odds.assign(observed_at=pd.to_datetime(odds["observed_at"], utc=True))
    g = log.assign(made_at=pd.to_datetime(log["made_at"], utc=True)).merge(games, on="game_id")
    g = g.set_index("game_id")

    # the price read in the prediction's own run (allow a second of clock skew between the two stamps)
    at_bet = _latest_before(odds, g["made_at"] + pd.Timedelta(seconds=1))
    fresh = at_bet["observed_at"] >= g.loc[at_bet.index, "made_at"] - pd.Timedelta(minutes=cfg["max_price_age_min"])
    at_bet = at_bet[fresh]
    close = _latest_before(odds, g["start_time_utc"])
    g = g.loc[at_bet.index]
    if g.empty:
        return pd.DataFrame(columns=BET_COLS)

    out = pd.DataFrame({
        "start_utc": g["start_time_utc"], "away": g["away_abbrev"], "home": g["home_abbrev"], "made_at": g["made_at"],
        "lineup": g["lineup"], "p_home": g["p_home"].astype(float),
        "home_ml": at_bet["home_ml"].astype(int), "away_ml": at_bet["away_ml"].astype(int), "book": at_bet["book"],
    })
    out["p_mkt_home"] = devig(out["home_ml"].to_numpy(), out["away_ml"].to_numpy(), cfg["devig"])
    out["edge_home"] = out["p_home"] - out["p_mkt_home"]
    e = cfg["min_edge"] - 1e-9
    out["side"] = np.where(out["edge_home"] >= e, "home", np.where(out["edge_home"] <= -e, "away", ""))
    bet = out["side"] != ""
    out["price"] = np.where(out["side"] == "home", out["home_ml"], np.where(out["side"] == "away", out["away_ml"], np.nan))
    out["stake"] = np.where(bet, float(cfg["stake"]), 0.0)

    out["close_home_ml"] = close["home_ml"].reindex(out.index)
    out["close_away_ml"] = close["away_ml"].reindex(out.index)
    has_close = out["close_home_ml"].notna()
    p_close = pd.Series(np.nan, index=out.index)
    if has_close.any():
        c = out[has_close]
        p_close[has_close] = devig(c["close_home_ml"].to_numpy(float), c["close_away_ml"].to_numpy(float), cfg["devig"])
    out["clv"] = np.where(out["side"] == "home", p_close - out["p_mkt_home"],
                          np.where(out["side"] == "away", out["p_mkt_home"] - p_close, np.nan))

    won = np.where(out["side"] == "home", g["home_win"] == 1, g["home_win"] == 0)
    final = g["home_win"].notna()
    started = out["start_utc"] <= now
    out["status"] = np.where(~bet, "pass", np.where(final, np.where(won, "won", "lost"),
                                                    np.where(started, "pending", "open")))
    dec = american_to_decimal(np.where(bet, out["price"], 100))
    out["profit"] = np.where(out["status"] == "won", out["stake"] * (dec - 1),
                             np.where(out["status"] == "lost", -out["stake"], np.nan))
    out = out.reset_index()
    for c in ("start_utc", "made_at"):
        out[c] = out[c].map(lambda t: t.isoformat())
    return out[BET_COLS].sort_values(["start_utc", "game_id"]).reset_index(drop=True)


def summary(bets: pd.DataFrame, cfg: dict) -> dict:
    """Headline numbers and the bankroll curve over settled bets, in start order."""
    placed = bets[bets["side"].fillna("") != ""]
    done = placed[placed["status"].isin(["won", "lost"])]
    staked = float(done["stake"].sum())
    profit = float(done["profit"].sum())
    clv = placed["clv"].dropna()
    return {
        "games_priced": int(len(bets)), "bets": int(len(placed)), "settled": int(len(done)),
        "won": int((done["status"] == "won").sum()), "lost": int((done["status"] == "lost").sum()),
        "open": int(placed["status"].isin(["open", "pending"]).sum()),
        "staked": round(staked, 2), "profit": round(profit, 2), "roi": round(profit / staked, 4) if staked else None,
        "bankroll_start": float(cfg["bankroll"]), "bankroll": round(float(cfg["bankroll"]) + profit, 2),
        "avg_edge": round(float(np.where(placed["side"] == "home", placed["edge_home"], -placed["edge_home"]).mean()), 4)
                    if len(placed) else None,
        "avg_clv": round(float(clv.mean()), 4) if len(clv) else None,
        "beat_close": round(float((clv > 0).mean()), 4) if len(clv) else None,
        "curve": [round(float(cfg["bankroll"]) + x, 2) for x in done["profit"].cumsum()],
    }
