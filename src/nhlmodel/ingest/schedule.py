"""Build the games table (one row per completed regular-season game) from cached schedule weeks."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

import pandas as pd

from . import nhl
from .http import CachedClient

COMPLETED_STATES = {"OFF", "FINAL"}


def _parse_game(g: dict[str, Any]) -> dict[str, Any]:
    h, a = g["homeTeam"], g["awayTeam"]
    return {
        "game_id": g["id"],
        "season": g["season"],
        "game_type": g["gameType"],
        "start_time_utc": pd.Timestamp(g["startTimeUTC"]),
        "venue_utc_offset": g.get("venueUTCOffset"),
        "venue_timezone": g.get("venueTimezone"),
        "neutral_site": bool(g.get("neutralSite", False)),
        "home_team_id": h["id"],
        "home_abbrev": h["abbrev"],
        "away_team_id": a["id"],
        "away_abbrev": a["abbrev"],
        "home_score": h.get("score"),
        "away_score": a.get("score"),
        "last_period_type": (g.get("gameOutcome") or {}).get("lastPeriodType"),
        "game_state": g.get("gameState"),
        "schedule_state": g.get("gameScheduleState"),
    }


def season_games(c: CachedClient, season: int, game_types: Iterable[int] = (2,), snapshot: str | None = None,
                 through: date | None = None) -> pd.DataFrame:
    """Walk the season's schedule week by week from its start date to its regular-season end date
    (or ``through``, for the current season). ``snapshot`` fetches weeks as dated copies."""
    meta = nhl.season_meta(c, season)
    start = date.fromisoformat(meta["startDate"][:10])
    end = date.fromisoformat(meta["regularSeasonEndDate"][:10])
    if through is not None:
        end = min(end, through)
    rows: dict[int, dict[str, Any]] = {}
    d = start
    while d <= end:
        week = nhl.schedule_week(c, d.isoformat(), snapshot)
        for day in week["gameWeek"]:
            for g in day["games"]:
                if g["season"] == season and g["gameType"] in set(game_types):
                    rows[g["id"]] = _parse_game(g)
        nxt = week.get("nextStartDate")
        d = date.fromisoformat(nxt) if nxt else d + timedelta(days=7)

    df = pd.DataFrame(rows.values()).sort_values(["start_time_utc", "game_id"]).reset_index(drop=True)
    df.attrs["expected_regular_season_games"] = meta.get("totalRegularSeasonGames")
    return df


def finalize(df: pd.DataFrame) -> pd.DataFrame:
    """Keep completed, non-cancelled games and add the target.

    Target: home team won, including overtime and shootout (standard NHL 2-way moneyline settlement).
    """
    done = df[df["game_state"].isin(COMPLETED_STATES) & (df["schedule_state"] == "OK")].copy()
    if (done["home_score"] == done["away_score"]).any():
        raise ValueError("completed game with tied final score")
    done["home_win"] = (done["home_score"] > done["away_score"]).astype("int8")
    done["decided_in"] = done["last_period_type"].map({"REG": "REG", "OT": "OT", "SO": "SO"})
    done["local_date"] = [local_date(t, off) for t, off in zip(done["start_time_utc"], done["venue_utc_offset"])]
    return done.reset_index(drop=True)


UPCOMING_STATES = {"FUT", "PRE"}
IN_PROGRESS_STATES = {"LIVE", "CRIT"}


def upcoming(df: pd.DataFrame, now: pd.Timestamp, days: float) -> pd.DataFrame:
    """Games not final yet: those that haven't started, starting within ``days`` of ``now``, plus games in
    progress (kept so rest days and back-to-backs for the next games are right; they are never predicted,
    since they've started). No outcome columns."""
    t = df["start_time_utc"]
    ok = df["schedule_state"] == "OK"
    soon = df["game_state"].isin(UPCOMING_STATES) & (t >= now) & (t <= now + pd.Timedelta(days=days))
    up = df[ok & (soon | df["game_state"].isin(IN_PROGRESS_STATES))].copy()
    up["local_date"] = [local_date(t, off) for t, off in zip(up["start_time_utc"], up["venue_utc_offset"])]
    return up.drop(columns=["home_score", "away_score", "last_period_type"]).reset_index(drop=True)


def local_date(start_utc: pd.Timestamp, utc_offset: str | None) -> date:
    """Game date in the venue's local time, e.g. 00:00Z with offset -05:00 -> previous day."""
    if not utc_offset:
        raise ValueError("missing venue UTC offset")
    sign = -1 if utc_offset.startswith("-") else 1
    hh, mm = utc_offset.lstrip("+-").split(":")
    return (start_utc + sign * pd.Timedelta(hours=int(hh), minutes=int(mm))).date()
