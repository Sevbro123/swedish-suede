"""Parse raw NHL JSON (play-by-play, boxscore, shift charts) into flat rows.

Pure functions of one raw document each; no I/O. Field names were verified live in Phase 0.

situationCode is a 4-digit string read as
    [away goalie in net][away skaters][home skaters][home goalie in net]
(verified: an away-team minor penalty is followed by "1451", a home-team minor by "1541").
"""
from __future__ import annotations

from typing import Any

SHOT_TYPES = ("shot-on-goal", "missed-shot", "blocked-shot", "goal")
SHIFT_TYPE_CODE = 517  # 505 rows in shift charts are goal markers, not shifts


def mmss(s: str | None) -> int | None:
    if not s:
        return None
    m, sec = s.split(":")
    return int(m) * 60 + int(sec)


def situation(code: str | None) -> dict[str, int | None]:
    keys = ("away_goalie_in", "away_skaters", "home_skaters", "home_goalie_in")
    if not code or len(code) != 4 or not code.isdigit():
        return dict.fromkeys(keys)
    return {k: int(c) for k, c in zip(keys, code)}


def parse_pbp(doc: dict[str, Any]) -> list[dict[str, Any]]:
    gid = doc["id"]
    home_id, away_id = doc["homeTeam"]["id"], doc["awayTeam"]["id"]
    player_team = {r["playerId"]: r["teamId"] for r in doc.get("rosterSpots", [])}
    rows = []
    for p in doc["plays"]:
        d = p.get("details") or {}
        pd_ = p.get("periodDescriptor") or {}
        typ = p["typeDescKey"]
        period = pd_.get("number")
        t = mmss(p.get("timeInPeriod"))
        shooter = d.get("shootingPlayerId") or d.get("scoringPlayerId")
        # Shooting team from the roster, not eventOwnerTeamId (ambiguous on blocked shots).
        if typ in SHOT_TYPES:
            team = player_team.get(shooter, d.get("eventOwnerTeamId"))
        else:
            team = d.get("eventOwnerTeamId")
        rows.append(
            {
                "game_id": gid,
                "event_id": p.get("eventId"),
                "sort_order": p.get("sortOrder"),
                "period": period,
                "period_type": pd_.get("periodType"),
                "t_period_s": t,
                "t_game_s": None if period is None or t is None else (period - 1) * 1200 + t,
                "type": typ,
                "situation_code": p.get("situationCode"),
                **situation(p.get("situationCode")),
                "home_defending_side": p.get("homeTeamDefendingSide"),
                "event_team_id": team,
                "is_home_event": None if team is None else team == home_id,
                "x": d.get("xCoord"),
                "y": d.get("yCoord"),
                "zone_code": d.get("zoneCode"),
                "shot_type": d.get("shotType"),
                "reason": d.get("reason"),
                "shooter_id": shooter,
                "goalie_id": d.get("goalieInNetId"),
                "blocker_id": d.get("blockingPlayerId"),
                "assist1_id": d.get("assist1PlayerId"),
                "assist2_id": d.get("assist2PlayerId"),
                "pen_type": d.get("typeCode") if typ == "penalty" else None,
                "pen_desc": d.get("descKey"),
                "pen_minutes": d.get("duration"),
                "committed_by_id": d.get("committedByPlayerId"),
                "drawn_by_id": d.get("drawnByPlayerId"),
                "home_team_id": home_id,
                "away_team_id": away_id,
            }
        )
    return rows


def parse_roster(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Players listed for the game in play-by-play rosterSpots (both teams)."""
    home_id = doc["homeTeam"]["id"]
    return [
        {
            "game_id": doc["id"],
            "team_id": r["teamId"],
            "is_home": r["teamId"] == home_id,
            "player_id": r["playerId"],
            "position": r.get("positionCode"),
        }
        for r in doc.get("rosterSpots", [])
    ]


def parse_goalie_games(rows: list[dict[str, Any]], home_away_ids: dict[int, tuple[int, int]]) -> list[dict[str, Any]]:
    """Bulk stats-API goalie-game rows -> goalie_games. ``home_away_ids`` maps game_id -> (home_id, away_id)."""
    out = []
    for r in rows:
        gid = r["gameId"]
        if gid not in home_away_ids:
            continue
        is_home = r["homeRoad"] == "H"
        out.append(
            {
                "game_id": gid,
                "team_id": home_away_ids[gid][0 if is_home else 1],
                "is_home": is_home,
                "player_id": r["playerId"],
                "starter": r.get("gamesStarted") == 1,
                "toi_s": r.get("timeOnIce"),
                "shots_against": r.get("shotsAgainst"),
                "saves": r.get("saves"),
                "goals_against": r.get("goalsAgainst"),
            }
        )
    return out


def _saves_shots(s: str | None) -> tuple[int | None, int | None]:
    if not s or "/" not in s:
        return None, None
    a, b = s.split("/")
    return int(a), int(b)


def parse_boxscore(doc: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (skater_rows, goalie_rows)."""
    gid = doc["id"]
    skaters, goalies = [], []
    for side in ("homeTeam", "awayTeam"):
        team_id = doc[side]["id"]
        block = doc["playerByGameStats"][side]
        for grp in ("forwards", "defense"):
            for r in block.get(grp, []):
                skaters.append(
                    {
                        "game_id": gid,
                        "team_id": team_id,
                        "is_home": side == "homeTeam",
                        "player_id": r["playerId"],
                        "position": r.get("position"),
                        "toi_s": mmss(r.get("toi")),
                        "goals": r.get("goals"),
                        "assists": r.get("assists"),
                        "sog": r.get("sog"),
                        "pim": r.get("pim"),
                        "hits": r.get("hits"),
                        "blocked_shots": r.get("blockedShots"),
                        "pp_goals": r.get("powerPlayGoals"),
                        "plus_minus": r.get("plusMinus"),
                        "shifts": r.get("shifts"),
                    }
                )
        for r in block.get("goalies", []):
            ev_sv, ev_sa = _saves_shots(r.get("evenStrengthShotsAgainst"))
            pp_sv, pp_sa = _saves_shots(r.get("powerPlayShotsAgainst"))
            sh_sv, sh_sa = _saves_shots(r.get("shorthandedShotsAgainst"))
            goalies.append(
                {
                    "game_id": gid,
                    "team_id": team_id,
                    "is_home": side == "homeTeam",
                    "player_id": r["playerId"],
                    "starter": r.get("starter"),
                    "toi_s": mmss(r.get("toi")),
                    "shots_against": r.get("shotsAgainst"),
                    "saves": r.get("saves"),
                    "goals_against": r.get("goalsAgainst"),
                    "ev_saves": ev_sv, "ev_shots_against": ev_sa,
                    "pp_saves": pp_sv, "pp_shots_against": pp_sa,
                    "sh_saves": sh_sv, "sh_shots_against": sh_sa,
                }
            )
    return skaters, goalies


def parse_shifts(doc: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for r in doc.get("data", []):
        if r.get("typeCode") != SHIFT_TYPE_CODE:
            continue
        start, end = mmss(r.get("startTime")), mmss(r.get("endTime"))
        rows.append(
            {
                "game_id": r["gameId"],
                "player_id": r["playerId"],
                "team_id": r["teamId"],
                "period": r["period"],
                "start_s": start,
                "end_s": end,
                "duration_s": mmss(r.get("duration")),
            }
        )
    return rows
