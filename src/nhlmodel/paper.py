"""Paper trading: the bets the live model would have made at the NHL partner book's prices, graded.

Nothing is stored beyond the two logs the live runs already keep, so the bets are rebuilt from them each
run and the rules can't drift from what was known at the time:

- the bet: each game's last prediction before puck drop (predictions_log.csv), at the price read in the
  same run (the newest odds-log row at most ``max_price_age_min`` before the prediction). It bets the side
  whose model chance beats the book's no-vig chance by ``min_edge`` or more (closer is a toss-up: no bet).
  The stake grows with the edge (``stake_tiers``); ``profit_flat`` is the same bet at ``flat_stake`` units,
  the original flat strategy kept as a benchmark.
- parlays: when 2+ games on one day clear ``parlay.min_edge``, the strongest (up to ``max_legs``) are also bet
  together. Unlike single bets, a parlay must be settled on before its first game starts, while later games'
  final predictions don't exist yet, so it is kept as state (paper_parlays.csv, one row per leg): each run
  re-picks a day's parlay from the open bets until one of its legs starts, then it is locked.
- the close: the newest price read before puck drop. Closing-line value (CLV) is the bet side's no-vig
  chance at the close minus at the bet: positive means the market moved toward us.
- settlement: 2-way moneyline, overtime and shootout included (games.parquet ``home_win``).

Writes paper_bets.csv: one row per game we had a price for, ``side`` empty when there was no bet.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .odds.vig import american_to_decimal, devig

BET_COLS = ["game_id", "date", "start_utc", "away", "home", "made_at", "lineup", "p_home", "home_ml", "away_ml",
            "book", "p_mkt_home", "edge_home", "side", "edge", "price", "stake", "close_home_ml", "close_away_ml",
            "clv", "status", "profit", "profit_flat"]
LEG_COLS = ["date", "game_id", "start_utc", "away", "home", "side", "price", "p", "p_mkt", "made_at", "stake"]


def stake_for(edge, tiers) -> np.ndarray:
    """Units for a bet with this edge (on its side): the highest tier it reaches, else 0."""
    edge = np.asarray(edge, float)
    out = np.zeros_like(edge)
    for lo, units in sorted(tiers):
        out = np.where(edge >= lo - 1e-9, float(units), out)
    return out


def _latest_before(odds: pd.DataFrame, cutoff: pd.Series) -> pd.DataFrame:
    """For each row of ``cutoff`` (indexed by game_id), the newest odds row observed strictly before it."""
    o = odds.merge(cutoff.rename("cutoff"), left_on="game_id", right_index=True)
    o = o[o["observed_at"] < o["cutoff"]]
    return o.sort_values("observed_at").groupby("game_id").tail(1).set_index("game_id")


def build_bets(log: pd.DataFrame, odds: pd.DataFrame, games: pd.DataFrame, cfg: dict, now: pd.Timestamp) -> pd.DataFrame:
    """``log``: predictions log (game_id, made_at, p_home, lineup). ``odds``: odds log. ``games``: game_id,
    start_time_utc, local_date, away_abbrev, home_abbrev and home_win (NaN until final), for every logged game."""
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
        "date": g["local_date"].astype(str), "start_utc": g["start_time_utc"], "away": g["away_abbrev"], "home": g["home_abbrev"], "made_at": g["made_at"],
        "lineup": g["lineup"], "p_home": g["p_home"].astype(float),
        "home_ml": at_bet["home_ml"].astype(int), "away_ml": at_bet["away_ml"].astype(int), "book": at_bet["book"],
    })
    out["p_mkt_home"] = devig(out["home_ml"].to_numpy(), out["away_ml"].to_numpy(), cfg["devig"])
    out["edge_home"] = out["p_home"] - out["p_mkt_home"]
    e = cfg["min_edge"] - 1e-9
    out["side"] = np.where(out["edge_home"] >= e, "home", np.where(out["edge_home"] <= -e, "away", ""))
    bet = out["side"] != ""
    out["price"] = np.where(out["side"] == "home", out["home_ml"], np.where(out["side"] == "away", out["away_ml"], np.nan))
    out["edge"] = np.where(out["side"] == "home", out["edge_home"], np.where(out["side"] == "away", -out["edge_home"], np.nan))
    out["stake"] = np.where(bet, stake_for(out["edge"].fillna(0), cfg["stake_tiers"]), 0.0)

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
    unit = np.where(out["status"] == "won", dec - 1, np.where(out["status"] == "lost", -1.0, np.nan))
    out["profit"] = out["stake"] * unit
    out["profit_flat"] = np.where(bet, float(cfg["flat_stake"]), 0.0) * unit
    out = out.reset_index()
    for c in ("start_utc", "made_at"):
        out[c] = out[c].map(lambda t: t.isoformat())
    return out[BET_COLS].sort_values(["start_utc", "game_id"]).reset_index(drop=True)


def update_parlays(legs: pd.DataFrame, bets: pd.DataFrame, cfg: dict, now: pd.Timestamp) -> pd.DataFrame:
    """Re-pick each day's parlay from the open bets, except days whose parlay already has a leg under way."""
    pc = cfg["parlay"]
    legs = legs.copy()
    started = pd.to_datetime(legs["start_utc"], utc=True) <= now
    locked = set(legs.loc[started, "date"].astype(str))
    keep = legs[legs["date"].astype(str).isin(locked)]
    open_ = bets[(bets["status"] == "open") & (bets["edge"] >= pc["min_edge"] - 1e-9) & ~bets["date"].astype(str).isin(locked)]
    new = []
    for date, day in open_.groupby("date"):
        if len(day) < 2:
            continue
        top = day.sort_values("edge", ascending=False).head(pc["max_legs"])
        home = top["side"] == "home"
        new.append(pd.DataFrame({
            "date": str(date), "game_id": top["game_id"], "start_utc": top["start_utc"], "away": top["away"],
            "home": top["home"], "side": top["side"], "price": top["price"].astype(int),
            "p": np.where(home, top["p_home"], 1 - top["p_home"]),
            "p_mkt": np.where(home, top["p_mkt_home"], 1 - top["p_mkt_home"]),
            "made_at": top["made_at"], "stake": float(pc["stake"])}))
    out = pd.concat([keep, *new], ignore_index=True) if new else keep
    return out[LEG_COLS].sort_values(["date", "start_utc", "game_id"]).reset_index(drop=True)


def grade_parlays(legs: pd.DataFrame, results: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """One row per parlay: combined price, model chance, status and profit. ``results``: game_id, home_win."""
    cols = ["date", "legs", "n_legs", "decimal", "p", "p_mkt", "stake", "first_start", "last_start", "status", "profit"]
    if legs.empty:
        return pd.DataFrame(columns=cols)
    lg = legs.merge(results[["game_id", "home_win"]], on="game_id", how="left")
    lg["won"] = np.where(lg["side"] == "home", lg["home_win"] == 1, lg["home_win"] == 0)
    lg["final"] = lg["home_win"].notna()
    lg["dec"] = american_to_decimal(lg["price"].astype(float))
    rows = []
    for date, d in lg.groupby("date"):
        dec, stake = float(d["dec"].prod()), float(d["stake"].iloc[0])
        if (d["final"] & ~d["won"]).any():
            status, profit = "lost", -stake
        elif d["final"].all():
            status, profit = "won", stake * (dec - 1)
        else:
            status = "pending" if (pd.to_datetime(d["start_utc"], utc=True) <= now).any() else "open"
            profit = np.nan
        rows.append({"date": str(date), "legs": " + ".join(f"{(r.home if r.side == 'home' else r.away)} {int(r.price):+d}"
                                                            for r in d.itertuples()),
                     "n_legs": int(len(d)), "decimal": round(dec, 3), "p": float(d["p"].prod()), "p_mkt": float(d["p_mkt"].prod()),
                     "stake": stake, "first_start": d["start_utc"].min(), "last_start": d["start_utc"].max(),
                     "status": status, "profit": profit})
    return pd.DataFrame(rows, columns=cols)


def summary(bets: pd.DataFrame, parlays: pd.DataFrame, cfg: dict) -> dict:
    """Headline numbers for the blended strategy (tiered singles + parlays) and the flat benchmark, plus both
    bankroll curves over settled bets in the order they settled (a parlay settles with its last game)."""
    placed = bets[bets["side"].fillna("") != ""]
    done = placed[placed["status"].isin(["won", "lost"])]
    pdone = parlays[parlays["status"].isin(["won", "lost"])] if len(parlays) else parlays
    staked = float(done["stake"].sum()) + (float(pdone["stake"].sum()) if len(pdone) else 0.0)
    profit = float(done["profit"].sum()) + (float(pdone["profit"].sum()) if len(pdone) else 0.0)
    flat_staked = float(cfg["flat_stake"]) * len(done)
    flat_profit = float(done["profit_flat"].sum())
    clv = placed["clv"].dropna()
    ev = pd.concat([done.assign(t=done["start_utc"])[["t", "profit", "profit_flat"]],
                    pdone.assign(t=pdone["last_start"], profit_flat=0.0)[["t", "profit", "profit_flat"]] if len(pdone) else None])
    ev = ev.sort_values("t", kind="stable") if len(ev) else ev
    b0 = float(cfg["bankroll"])
    return {
        "games_priced": int(len(bets)), "bets": int(len(placed)), "settled": int(len(done)),
        "won": int((done["status"] == "won").sum()), "lost": int((done["status"] == "lost").sum()),
        "open": int(placed["status"].isin(["open", "pending"]).sum()),
        "parlays": int(len(parlays)), "parlays_won": int((parlays["status"] == "won").sum()) if len(parlays) else 0,
        "parlays_settled": int(len(pdone)),
        "staked": round(staked, 2), "profit": round(profit, 2), "roi": round(profit / staked, 4) if staked else None,
        "bankroll_start": b0, "bankroll": round(b0 + profit, 2),
        "flat": {"staked": round(flat_staked, 2), "profit": round(flat_profit, 2), "bankroll": round(b0 + flat_profit, 2),
                 "roi": round(flat_profit / flat_staked, 4) if flat_staked else None},
        "avg_edge": round(float(placed["edge"].mean()), 4) if len(placed) else None,
        "avg_stake": round(float(placed["stake"].mean()), 2) if len(placed) else None,
        "avg_clv": round(float(clv.mean()), 4) if len(clv) else None,
        "beat_close": round(float((clv > 0).mean()), 4) if len(clv) else None,
        "curve": [round(b0 + x, 2) for x in ev["profit"].cumsum()] if len(ev) else [],
        "curve_flat": [round(b0 + x, 2) for x in ev["profit_flat"].cumsum()] if len(ev) else [],
    }
