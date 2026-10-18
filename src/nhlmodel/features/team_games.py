"""Per-team, per-game box stats derived from play-by-play events.

One row per (game_id, team_id) with counts for and against. These are *outcomes of game G*;
they may only feed features for games that start after G (enforced in ``asof.py``).

Definitions (shootout events excluded throughout):
- corsi (shot attempts) = goals + shots on goal + missed + blocked
- fenwick (unblocked attempts) = goals + shots on goal + missed
- sog = shots on goal + goals
- 5v5 = both goalies in net and 5 skaters a side (situation code "1551")
- pp/pk = this team has more/fewer skaters than the opponent, both goalies in net
- strength-state time: each event's situation is assumed to hold until the next event,
  so state durations are approximations at event resolution.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SHOTS = {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}


def _strength(ev: pd.DataFrame) -> pd.DataFrame:
    """Per event, from the shooting/acting team's perspective: own and opponent skaters."""
    home = ev["is_home_event"].astype("boolean")
    own = np.where(home, ev["home_skaters"], ev["away_skaters"])
    opp = np.where(home, ev["away_skaters"], ev["home_skaters"])
    goalies_in = (ev["home_goalie_in"] == 1) & (ev["away_goalie_in"] == 1)
    return pd.DataFrame({"own": own, "opp": opp, "goalies_in": goalies_in}, index=ev.index)


def _state_seconds(ev: pd.DataFrame) -> pd.DataFrame:
    """Seconds per game in 5v5 / home-PP / away-PP states, from event-to-event intervals."""
    e = ev[ev["period_type"] != "SO"].sort_values(["game_id", "sort_order"])
    dt = e.groupby("game_id")["t_game_s"].diff(-1).abs().fillna(0)
    dt = dt.where(e["period"] == e.groupby("game_id")["period"].shift(-1), 0)  # don't span periods
    both = (e["home_goalie_in"] == 1) & (e["away_goalie_in"] == 1)
    s = pd.DataFrame(
        {
            "game_id": e["game_id"],
            "t_5v5": dt.where(both & (e["home_skaters"] == 5) & (e["away_skaters"] == 5), 0),
            "t_home_pp": dt.where(both & (e["home_skaters"] > e["away_skaters"]), 0),
            "t_away_pp": dt.where(both & (e["away_skaters"] > e["home_skaters"]), 0),
        }
    )
    return s.groupby("game_id").sum()


def build_team_games(events: pd.DataFrame, games: pd.DataFrame, xg: pd.DataFrame | None = None) -> pd.DataFrame:
    """``xg`` (game_id, event_id, xg) adds xg_for/against and xg_5v5; absent shots count as 0,
    and games with no xG at all (burn-in season) get NaN."""
    ev = events[events["period_type"] != "SO"].copy()
    if xg is not None:
        ev = ev.merge(xg[["game_id", "event_id", "xg"]], on=["game_id", "event_id"], how="left")
    ev = ev[ev["event_team_id"].notna()]
    st = _strength(ev)
    shot = ev["type"].isin(SHOTS)
    cols = pd.DataFrame(
        {
            "game_id": ev["game_id"],
            "team_id": ev["event_team_id"].astype("int64"),
            "goals": (ev["type"] == "goal").astype(int),
            "sog": ev["type"].isin({"goal", "shot-on-goal"}).astype(int),
            "fenwick": ev["type"].isin({"goal", "shot-on-goal", "missed-shot"}).astype(int),
            "corsi": shot.astype(int),
        }
    )
    is5 = st["goalies_in"] & (st["own"] == 5) & (st["opp"] == 5)
    has_xg = xg is not None
    if has_xg:
        cols["xg"] = ev["xg"].fillna(0.0)
    for c in ("goals", "sog", "fenwick", "corsi") + (("xg",) if has_xg else ()):
        cols[f"{c}_5v5"] = cols[c] * is5
    cols["pp_goals"] = cols["goals"] * (st["goalies_in"] & (st["own"] > st["opp"]))
    cols["sh_goals"] = cols["goals"] * (st["goalies_in"] & (st["own"] < st["opp"]))
    pen = (ev["type"] == "penalty") & (ev["pen_minutes"].fillna(0) > 0)
    cols["penalties"] = pen.astype(int)  # penalty events are owned by the committing team (verified)
    cols["pim"] = ev["pen_minutes"].fillna(0).where(pen, 0)

    own = cols.groupby(["game_id", "team_id"]).sum()

    g = games[["game_id", "season", "start_time_utc", "home_team_id", "away_team_id"]]
    sides = pd.concat(
        [
            g.assign(team_id=g["home_team_id"], opp_id=g["away_team_id"], is_home=True),
            g.assign(team_id=g["away_team_id"], opp_id=g["home_team_id"], is_home=False),
        ]
    )[["game_id", "season", "start_time_utc", "team_id", "opp_id", "is_home"]]

    stat_cols = list(own.columns)
    tg = sides.merge(own, left_on=["game_id", "team_id"], right_index=True, how="left")
    opp = own.rename(columns={c: f"{c}_against" for c in stat_cols})
    tg = tg.merge(opp, left_on=["game_id", "opp_id"], right_index=True, how="left")
    tg = tg.rename(columns={c: f"{c}_for" for c in stat_cols})
    num = [c for c in tg.columns if (c.endswith("_for") or c.endswith("_against")) and not c.startswith("xg")]
    tg[num] = tg[num].fillna(0).astype("int64")
    if has_xg:
        scored = set(xg["game_id"].unique())
        for c in [c for c in tg.columns if c.startswith("xg")]:
            tg[c] = tg[c].fillna(0.0).where(tg["game_id"].isin(scored))

    t = _state_seconds(events)
    tg = tg.merge(t, left_on="game_id", right_index=True, how="left")
    tg["toi_5v5_s"] = tg["t_5v5"]
    tg["toi_pp_s"] = np.where(tg["is_home"], tg["t_home_pp"], tg["t_away_pp"])
    tg["toi_pk_s"] = np.where(tg["is_home"], tg["t_away_pp"], tg["t_home_pp"])
    tg = tg.drop(columns=["t_5v5", "t_home_pp", "t_away_pp"])
    return tg.sort_values(["start_time_utc", "game_id", "is_home"]).reset_index(drop=True)
