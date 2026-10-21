# When lineups post, and when the live runs start

Observed on the night of 2026-10-20/21 (11 games, puck drops 23:00 to 02:30 UTC), from the live
workflow's own logs: 5 scheduled runs plus 7 extra manual runs as probes. Each run logs, for every game
within 2 h of puck drop, whether play-by-play `rosterSpots` holds a lineup.

## Scheduled runs started late or never

| Cron (UTC) | Run created | Delay |
|---|---|---|
| 14:15 | 18:26:59 | 4 h 12 min |
| 22:35 | none | dropped |
| 23:35 | none | dropped |
| 00:35 | 00:51:40 | 17 min |
| 01:35 | none | dropped |
| 02:35 | none by 03:10 | dropped |

Manual (`workflow_dispatch`) runs all started within 10 s. Without the probes, 10 of the 11 games would
have been predicted only by the 18:27 run, with projected lineups.

## rosterSpots fills in two steps

`rosterSpots` first lists each team's full roster (22-23 players, scratches included). That had already
happened at 22:07 for all seven games starting by 00:00, up to 113 minutes before puck drop. Under the old
rule (18 or more players), the runs at 22:07 and 22:22 took those full rosters as "confirmed". Commit
a17cb12 now accepts only the trimmed 18-20 player list. Every observation below uses that rule (runs from
22:52 on):

| Game | Puck drop | Last seen not posted | First seen posted |
|---|---|---|---|
| SJS@MTL, COL@NJD, LAK@WSH, TOR@CBJ | 23:00 | none seen | 22:52 (T-8) |
| ANA@NYI | 23:00 | 22:52 (T-8) | 23:52 (after start) |
| WPG@STL | 00:00 | 22:52 (T-68) | 23:52 (T-8) |
| BOS@DAL | 00:00 | 23:52 (T-8) | 00:52 (after start) |
| MIN@EDM | 01:00 | 00:52 (T-8) | 00:54 (T-6) |
| DET@SEA | 01:40 | 01:22 (T-18) | 02:17 (after start) |
| CAR@VAN | 02:00 | 01:22 (T-38) | 02:17 (after start) |
| TBL@VGK | 02:30 | 02:17 (T-13) | not seen before start |

The dressed lineup shows up between about 15 and 5 minutes before puck drop, and sometimes only after.
None of tonight's lineups were posted 25 minutes out, so the old schedule (one run 25 to 55 minutes before each game)
could not have caught them even if every run had started on time. 6 of the 11 games got a confirmed-lineup
prediction tonight, all from runs 6 to 8 minutes before puck drop.

## What changed

`python -m nhlmodel.watch` (used by `.github/workflows/live.yml`) runs the pipeline once, then stays up
through the game window. It polls the rosterSpots of games starting within 25 minutes every minute, and
reruns and republishes as soon as a lineup posts. A rerun takes about 2 minutes, so a lineup posted at T-6
still makes it. A run stays up only while a game starts within 90 minutes, and at most 3 h (first version:
4 h and 5.5 h, tightened on 2026-10-21 to cut idle runner time and how long a stuck run could block the
queue). Triggers every 30 minutes from 13:07 to 03:37 UTC queue behind a running watcher (GitHub keeps one
pending run per concurrency group), so each game gets about three chances to start a watcher in time, and
matinees are covered.

Open: a lineup that posts after puck drop (4 of 11 tonight) can't be used. Whether another NHL source posts
lineups earlier hasn't been checked. Each run now logs per-team counts (e.g. `confirmed (20/20)`,
`not posted yet (23/22)`), so later nights can be tallied from the run logs.
