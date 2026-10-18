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


def shift_chart(c: CachedClient, game_id: int) -> dict[str, Any]:
    return c.get_json(
        f"{STATS}/shiftcharts?cayenneExp=gameId={game_id}", f"nhl_stats/shifts/{game_id // 1000000}/{game_id}"
    )
