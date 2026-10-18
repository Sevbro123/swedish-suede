"""NHL public endpoints (unofficial; verified in Phase 0, see docs/phase0_data_discovery.md).

Each function maps one endpoint to a stable cache key. Only call these for
completed seasons/games: the raw cache is write-once, so anything that can
still change (today's schedule, games in progress) must not be cached here.
"""
from __future__ import annotations

from typing import Any

from .http import CachedClient

WEB = "https://api-web.nhle.com/v1"
STATS = "https://api.nhle.com/stats/rest/en"


def season_meta(c: CachedClient, season: int) -> dict[str, Any]:
    data = c.get_json(f"{STATS}/season?cayenneExp=id={season}", f"nhl_stats/season/{season}")
    rows = data["data"]
    if len(rows) != 1:
        raise ValueError(f"expected 1 season row for {season}, got {len(rows)}")
    return rows[0]


def schedule_week(c: CachedClient, date: str) -> dict[str, Any]:
    """7-day schedule window starting at ``date`` (YYYY-MM-DD)."""
    return c.get_json(f"{WEB}/schedule/{date}", f"nhl_web/schedule/{date}")


def play_by_play(c: CachedClient, game_id: int) -> dict[str, Any]:
    return c.get_json(f"{WEB}/gamecenter/{game_id}/play-by-play", f"nhl_web/pbp/{game_id // 1000000}/{game_id}")


def boxscore(c: CachedClient, game_id: int) -> dict[str, Any]:
    return c.get_json(f"{WEB}/gamecenter/{game_id}/boxscore", f"nhl_web/boxscore/{game_id // 1000000}/{game_id}")


def goalie_games(c: CachedClient, season: int, game_type: int = 2) -> list[dict[str, Any]]:
    """Every goalie appearance in a season, one row per goalie-game, in a single request.

    Includes gamesStarted (the starter flag), timeOnIce (s), shotsAgainst, saves, goalsAgainst,
    homeRoad. Replaces per-game boxscores for goalie data.
    """
    url = (
        f"{STATS}/goalie/summary?isAggregate=false&isGame=true&start=0&limit=-1&sort=gameId"
        f"&cayenneExp=seasonId={season}%20and%20gameTypeId={game_type}"
    )
    data = c.get_json(url, f"nhl_stats/goalie_games/{season}_{game_type}")
    if len(data["data"]) != data["total"]:
        raise ValueError(f"goalie_games {season}: got {len(data['data'])} of {data['total']} rows")
    return data["data"]


def shift_chart(c: CachedClient, game_id: int) -> dict[str, Any]:
    return c.get_json(
        f"{STATS}/shiftcharts?cayenneExp=gameId={game_id}", f"nhl_stats/shifts/{game_id // 1000000}/{game_id}"
    )
