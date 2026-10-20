"""NHL public endpoints (unofficial; verified in Phase 0, see docs/phase0_data_discovery.md).

Each function maps one endpoint to a stable cache key. The raw cache is write-once, so anything
that can still change (the current season's schedule, games final for less than a day, the
current season's goalie table) is fetched with ``snapshot=<UTC timestamp>``: the key gets a
``snap/<timestamp>/`` prefix, so each fetch is kept as its own immutable copy and processing
reads the newest one (``latest_snapshot``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .http import CachedClient

WEB = "https://api-web.nhle.com/v1"
STATS = "https://api.nhle.com/stats/rest/en"
SNAP = "snap"


def _key(key: str, snapshot: str | None) -> str:
    return f"{SNAP}/{snapshot}/{key}" if snapshot else key


def latest_snapshot(raw_dir: Path, key: str, suffix: str = ".json.gz") -> Path | None:
    """Newest snapshot copy of ``key`` (timestamps sort as strings), or None."""
    hits = sorted((raw_dir / SNAP).glob(f"*/{key}{suffix}"))
    return hits[-1] if hits else None


def season_meta(c: CachedClient, season: int) -> dict[str, Any]:
    data = c.get_json(f"{STATS}/season?cayenneExp=id={season}", f"nhl_stats/season/{season}")
    rows = data["data"]
    if len(rows) != 1:
        raise ValueError(f"expected 1 season row for {season}, got {len(rows)}")
    return rows[0]


def schedule_week(c: CachedClient, date: str, snapshot: str | None = None) -> dict[str, Any]:
    """7-day schedule window starting at ``date`` (YYYY-MM-DD)."""
    return c.get_json(f"{WEB}/schedule/{date}", _key(f"nhl_web/schedule/{date}", snapshot))


def play_by_play(c: CachedClient, game_id: int, snapshot: str | None = None) -> dict[str, Any]:
    return c.get_json(f"{WEB}/gamecenter/{game_id}/play-by-play",
                      _key(f"nhl_web/pbp/{game_id // 1000000}/{game_id}", snapshot))


def boxscore(c: CachedClient, game_id: int) -> dict[str, Any]:
    return c.get_json(f"{WEB}/gamecenter/{game_id}/boxscore", f"nhl_web/boxscore/{game_id // 1000000}/{game_id}")


def goalie_games(c: CachedClient, season: int, game_type: int = 2, snapshot: str | None = None) -> list[dict[str, Any]]:
    """Every goalie appearance in a season, one row per goalie-game, in a single request.

    Includes gamesStarted (the starter flag), timeOnIce (s), shotsAgainst, saves, goalsAgainst,
    homeRoad. Replaces per-game boxscores for goalie data.
    """
    url = (
        f"{STATS}/goalie/summary?isAggregate=false&isGame=true&start=0&limit=-1&sort=gameId"
        f"&cayenneExp=seasonId={season}%20and%20gameTypeId={game_type}"
    )
    data = c.get_json(url, _key(f"nhl_stats/goalie_games/{season}_{game_type}", snapshot))
    if len(data["data"]) != data["total"]:
        raise ValueError(f"goalie_games {season}: got {len(data['data'])} of {data['total']} rows")
    return data["data"]


def shift_chart(c: CachedClient, game_id: int, snapshot: str | None = None) -> dict[str, Any]:
    return c.get_json(
        f"{STATS}/shiftcharts?cayenneExp=gameId={game_id}", _key(f"nhl_stats/shifts/{game_id // 1000000}/{game_id}", snapshot)
    )
