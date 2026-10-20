# Score and venue adjustment: choices frozen on development seasons

Written and committed before any test-period result of these features was produced.

## What was added

`src/nhlmodel/features/adjust.py` adds score-adjusted (`_sa_`) and score-and-venue-adjusted (`_sva_`)
versions of 5v5 corsi, fenwick and xG to the team-game table. These go through the same windows as
the raw stats (`l5/l10/l20`, `std`, `ewm5/15`). Coefficients come only from earlier seasons
(score: 3 seasons, venue: 2 seasons, shrunk with 40 pseudo-games). All settings were fixed before
any model was run and were not tuned.

Sanity checks:
- The original 302 feature columns are bit-identical after the rebuild. Baseline B and the Phase 3
  logistic reproduce their stored dev predictions exactly; the Phase 3 `full` matrix excludes the
  new columns unless a config sets `features: full_adjusted`.
- Score weights (2018-19, from 2015-16 to 2017-18): trailing by 2+ ≈ 0.88, tied ≈ 1.00, leading by
  2+ ≈ 1.16, in line with published values.
- Venue factors (2018-19) range about 0.88 (NJD) to 1.06 (SJS) for 5v5 corsi.

## Development results (2012-13 to 2017-18, n = 6,911)

| Run | Dev log loss | Paired vs reference |
|---|---|---|
| Baseline B (reference) | 0.67560 | |
| B, score-adjusted 5v5 xG share (`adj_b_sa`) | 0.67545 | −0.00015 [−0.00022, −0.00008], better |
| B, score + venue adjusted (`adj_b_sva`) | 0.67548 | −0.00012 [−0.00025, +0.00000], within noise |
| `adj_b_sva` minus `adj_b_sa` | | +0.00003 [−0.00007, +0.00013], within noise |
| Phase 3 logistic C=0.001 (reference) | 0.67265 | |
| Same + all adjusted shares (`adj_logreg_full_C0.001`) | 0.67269 | +0.00004 [−0.00018, +0.00027], within noise |

Score adjustment gives a consistent but very small gain (about 0.02% of log loss). Venue
adjustment adds nothing on top of it. In the 173-column logistic, the adjusted columns are redundant
with the raw ones.

## Frozen for the test period

| Run | Config |
|---|---|
| `adj_b_sa` | `configs/experiments/adjust/adj_b_sa.yaml` |

Planned test comparison: `adj_b_sa` vs Baseline B (paired). The venue adjustment and the full-matrix
variant are not carried to the test period. No further changes after the test result.
