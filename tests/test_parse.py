from nhlmodel.ingest.parse import (
    mmss, parse_boxscore, parse_goalie_games, parse_pbp, parse_roster, parse_shifts, situation,
)

HOME, AWAY = 7, 30


def pbp_doc(plays):
    return {
        "id": 2023020204,
        "homeTeam": {"id": HOME},
        "awayTeam": {"id": AWAY},
        "rosterSpots": [{"teamId": HOME, "playerId": 1}, {"teamId": AWAY, "playerId": 2}],
        "plays": plays,
    }


def play(typ, details, period=1, t="05:00", code="1551", ptype="REG"):
    return {
        "eventId": 1,
        "sortOrder": 1,
        "typeDescKey": typ,
        "periodDescriptor": {"number": period, "periodType": ptype},
        "timeInPeriod": t,
        "situationCode": code,
        "details": details,
    }


def test_mmss():
    assert mmss("19:15") == 1155 and mmss("00:00") == 0 and mmss(None) is None and mmss("") is None


def test_situation_digit_order():
    assert situation("1451") == {"away_goalie_in": 1, "away_skaters": 4, "home_skaters": 5, "home_goalie_in": 1}
    assert situation("0651")["away_goalie_in"] == 0  # away net empty, extra attacker
    assert situation(None)["home_skaters"] is None


def test_blocked_shot_team_comes_from_shooter_roster_not_event_owner():
    # Event owner says the blocking (home) team, but the shooter is on the away roster.
    rows = parse_pbp(pbp_doc([play("blocked-shot", {"shootingPlayerId": 2, "blockingPlayerId": 1, "eventOwnerTeamId": HOME})]))
    assert rows[0]["event_team_id"] == AWAY and rows[0]["is_home_event"] is False


def test_goal_fields_and_game_clock():
    rows = parse_pbp(pbp_doc([play("goal", {"scoringPlayerId": 1, "goalieInNetId": 99, "xCoord": 80, "yCoord": -3,
                                            "shotType": "wrist", "eventOwnerTeamId": HOME}, period=3, t="02:30")]))
    r = rows[0]
    assert r["shooter_id"] == 1 and r["goalie_id"] == 99 and r["is_home_event"] is True
    assert r["t_game_s"] == 2 * 1200 + 150 and (r["x"], r["y"]) == (80, -3)


def test_penalty_fields():
    rows = parse_pbp(pbp_doc([play("penalty", {"typeCode": "MIN", "descKey": "tripping", "duration": 2,
                                               "committedByPlayerId": 2, "drawnByPlayerId": 1, "eventOwnerTeamId": AWAY})]))
    r = rows[0]
    assert (r["pen_type"], r["pen_minutes"], r["committed_by_id"], r["event_team_id"]) == ("MIN", 2, 2, AWAY)


def test_boxscore_goalies_and_skaters():
    doc = {
        "id": 1,
        "homeTeam": {"id": HOME},
        "awayTeam": {"id": AWAY},
        "playerByGameStats": {
            "homeTeam": {
                "forwards": [{"playerId": 10, "position": "C", "toi": "19:15", "goals": 1}],
                "defense": [],
                "goalies": [
                    {"playerId": 11, "starter": True, "toi": "60:00", "saveShotsAgainst": "28/30",
                     "evenStrengthShotsAgainst": "24/25", "shotsAgainst": 30, "saves": 28, "goalsAgainst": 2},
                    {"playerId": 12, "starter": False, "toi": "00:00", "evenStrengthShotsAgainst": "0/0"},
                ],
            },
            "awayTeam": {"forwards": [], "defense": [], "goalies": []},
        },
    }
    sk, gl = parse_boxscore(doc)
    assert sk[0]["toi_s"] == 1155 and sk[0]["is_home"] is True
    assert [g["starter"] for g in gl] == [True, False]
    assert (gl[0]["ev_saves"], gl[0]["ev_shots_against"]) == (24, 25)


def test_shifts_skip_goal_marker_rows():
    doc = {"data": [
        {"typeCode": 517, "gameId": 1, "playerId": 5, "teamId": HOME, "period": 1,
         "startTime": "00:00", "endTime": "00:34", "duration": "00:34"},
        {"typeCode": 505, "gameId": 1, "playerId": 5, "teamId": HOME, "period": 1,
         "startTime": "10:00", "endTime": "10:00", "duration": None},
    ]}
    rows = parse_shifts(doc)
    assert len(rows) == 1 and (rows[0]["start_s"], rows[0]["end_s"]) == (0, 34)


def test_roster_marks_home_players():
    rows = parse_roster(pbp_doc([]))
    assert {(r["player_id"], r["is_home"]) for r in rows} == {(1, True), (2, False)}


def test_bulk_goalie_rows_map_to_team_ids_and_skip_unknown_games():
    rows = [
        {"gameId": 100, "playerId": 11, "homeRoad": "H", "gamesStarted": 1, "timeOnIce": 3600, "shotsAgainst": 30,
         "saves": 28, "goalsAgainst": 2},
        {"gameId": 100, "playerId": 21, "homeRoad": "R", "gamesStarted": 0, "timeOnIce": 1200},
        {"gameId": 999, "playerId": 31, "homeRoad": "H", "gamesStarted": 1},
    ]
    out = parse_goalie_games(rows, {100: (HOME, AWAY)})
    assert [(r["player_id"], r["team_id"], r["starter"]) for r in out] == [(11, HOME, True), (21, AWAY, False)]


def test_clean_shifts_drops_foreign_teams_and_duplicates_and_flags_bad_toi():
    from nhlmodel.ingest.process import clean_shifts

    def sh(team, pid, start, end):
        return {"game_id": 1, "player_id": pid, "team_id": team, "period": 1, "start_s": start, "end_s": end,
                "duration_s": end - start}

    rows = [sh(HOME, 1, 0, 40), sh(HOME, 1, 0, 40), sh(AWAY, 2, 0, 40), sh(99, 3, 0, 40)]
    keep, info = clean_shifts(rows, HOME, AWAY)
    assert len(keep) == 2 and info["n_shifts_dropped"] == 2
    assert info["shifts_ok"] is False  # 40 s of TOI per team is far below a full game

    full = [sh(t, 100 * t + p, 0, 3600) for t in (HOME, AWAY) for p in range(6)]
    assert clean_shifts(full, HOME, AWAY)[1]["shifts_ok"] is True
