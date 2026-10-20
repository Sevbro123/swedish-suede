# Lineup features (quick version): choices frozen on development seasons

Written and committed before any test-period result of these features was produced.

## What was added

`src/nhlmodel/features/players.py`, the quick version of `docs/player_ratings_spec.md`, with no
teammate or opponent adjustment:

- Per skater-game, from shift charts: 5v5 TOI and on-ice / off-ice 5v5 xG for and against.
  Integrity check (2023-24): in every team-game, summed skater TOI and on-ice xG are 5.00× the team
  totals (mean 5.003 and 5.000).
- Per player, decayed over their last ~40 games across seasons and teams: on-ice xG share (shrunk
  toward 0.5), on-ice share relative to off-ice, and expected 5v5 TOI.
- Per team-game, weighted by expected TOI: `lineup_on_xg_share`, `lineup_rel_xg_share`,
  `lineup_missing_toi_share` (regulars not in the lineup). Projected lineup = the previous game's
  skaters (deployable); `leaky_` = the game's actual roster (upper bound only).

All settings were fixed in advance and not tuned (`configs/features/base.yaml`, `players:`).

Sanity checks:
- Every earlier feature column is bit-identical. Baseline B, the Phase 3 logistic and `adj_b_sa`
  reproduce their stored dev predictions exactly; the `full` matrix leaves lineup columns out
  unless `features: full_lineup`.
- Truncation check on real data (2013-14 to 2015-16, cutoff 2016-01-15): deleting every event,
  shift, xG and roster row from the cutoff on changes projected features at the cutoff by at most
  1e-16. The leaky variant changes, as it should.
- 1,129 of 826,636 shift rows in 2019-20 have no start or end time and are dropped.
- `lineup_on_xg_share` correlates 0.94 with the team's own season-to-date 5v5 xG share; the
  projected and actual lineup versions correlate 0.995.

## Development results (2012-13 to 2017-18, n = 6,911)

| Run | Dev log loss | Paired vs reference |
|---|---|---|
| Baseline B (reference) | 0.67560 | |
| B + projected lineup (`lu_b`) | 0.67426 | −0.00134 [−0.00222, −0.00044], better |
| B + actual lineup (`lu_b_leaky`, upper bound) | 0.67409 | −0.00151 [−0.00261, −0.00045] |
| Lineup instead of team xG share (`lu_no_team_xg`) | 0.67476 | −0.00085 [−0.00248, +0.00074], within noise |
| Phase 3 logistic C=0.001 (reference) | 0.67265 | |
| Same + projected lineup (`lu_logreg_full_C0.001`) | 0.67224 | −0.00041 [−0.00080, −0.00003], better |

Player-based features on their own do about as well as the team's xG history, and together they
improve on it. Knowing the actual lineup instead of projecting it from the previous game adds
little (0.00017).

## Frozen for the test period

| Run | Config | Planned paired comparison |
|---|---|---|
| `lu_b` | `configs/experiments/lineup/lu_b.yaml` | vs Baseline B |
| `lu_logreg_full_C0.001` | `configs/experiments/lineup/lu_logreg_full_C0.001.yaml` | vs `p3_logreg_C0.001` |
| `lu_b_leaky` | `configs/experiments/lineup/lu_b_leaky.yaml` | reported as upper bound only |

No further changes after the test results.
