# Player ratings (RAPM): choices frozen on development seasons

This was written and committed before any test-period result for these features existed. It is the
full version of `docs/player_ratings_spec.md`, with teammate and opponent adjustment.

## What was added

- `src/nhlmodel/ratings/stints.py` splits every game into 5v5 stints, where the ten skaters on the
  ice stay the same. Each stint records home and away xG and the score state. A stint counts as 5v5
  when the shift charts show five skaters and a goalie for each team. Play-by-play situation codes
  change only at events, so they miss the moment a penalty expires. A shot counts only if it is
  coded 1551, and it goes to the stint with start < t <= end, as in `players.py`.
  - Checks per game: the stints must recover at least 95% of the 5v5 xG and 98% of the 5v5 seconds.
    The spec's 1% xG tolerance failed 4-8% of games because of a single shot at a change that the
    shift charts timed differently. The median game recovers 100%.
  - Across 2011-12 to 2025-26, 96.6% of games pass and 99.6% of 5v5 xG is recovered. 2019-20 has the
    most failures (955 of 1,078 games pass).
- `src/nhlmodel/ratings/rapm.py` fits a ridge regression on xG per 60, weighted by stint minutes,
  with one row per stint and attacking team. Each player gets an offense coefficient and a defense
  coefficient. The model also has an intercept, a home term and the attacking team's
  trailing/leading state, which are not penalized. Ratings are refit at every month boundary on
  games that started before that month.
  - **Deviation from the spec:** the spec carried each player's previous rating forward as a prior.
    Instead, older stints are down-weighted by a half-life in calendar months, and the decay is
    applied to the summed normal equations. This also carries ratings across seasons, with a single
    setting. Players with no history are rated at 0 (league average), with no separate mean per
    position.
- `features/players.py: rapm_lineup_features` adds `rapm_off`, `rapm_def` and `rapm_net` for each
  team-game. Each skater's rating is weighted by their expected 5v5 TOI, scaled to five skaters on
  the ice. The projected lineup is the one from the previous game; the `leaky_` columns use the
  actual lineup. The `rapm` feature group adds the existing `lineup_missing_toi_share`.
- The Phase 3 "full" matrix leaves out `rapm_*` columns unless a config sets `features: full_rapm`
  (the full_lineup matrix plus `rapm_*`).

Sanity checks:
- Every earlier feature column is bit-identical after the rebuild, so frozen configs reproduce.
- Unit tests (`tests/test_rapm.py`) cover:
  - stint splitting at changes, with a pulled goalie ending 5v5
  - assigning a shot at a boundary to the stint that ends then
  - recovering planted offense and defense effects on synthetic stints
  - the as-of rule: ratings for month M are identical when every stint from M on is deleted
  - lineup weighting
- Face validity: as of March 2016, the top net ratings went to Bergeron, Thornton, Getzlaf and
  Kopitar.

## Tuning (development seasons only)

The grid used Baseline B + `rapm` (projected lineup) through the dev walk-forward. Ratings were fit
only up to the end of 2017-18. Full grid: `results/rapm_grid.csv`.

| Half-life (months) \ λ (minutes) | 100 | 300 | 1000 | 3000 |
|---|---|---|---|---|
| 12 | | 0.67383 | 0.67391 | 0.67410 |
| 24 | 0.67383 | **0.67373** | 0.67379 | 0.67396 |
| 48 | 0.67384 | 0.67374 | 0.67377 | 0.67393 |
| none | | 0.67380 | 0.67382 | 0.67396 |

The chosen settings are **λ = 300, half-life 24 months**. The grid is flat: everything is within
0.0004 of the best. Choosing from 14 settings flatters the dev result a little; the test run below
has no such selection.

## Development results (2012-13 to 2017-18, n = 6,911)

| Run | Dev log loss | Paired vs reference |
|---|---|---|
| Baseline B (reference) | 0.67560 | |
| B + RAPM, projected lineup (`rp_b`) | 0.67373 | −0.00187 [−0.00305, −0.00075], better |
| B + RAPM, actual lineup (`rp_b_leaky`, upper bound) | 0.67344 | −0.00217 [−0.00356, −0.00083] |
| RAPM instead of team xG share (`rp_no_team_xg`) | 0.67495 | −0.00065 [−0.00288, +0.00157], within noise |
| B + quick lineup features (`lu_b`, reference) | 0.67426 | |
| `rp_b` vs `lu_b` | | −0.00054 [−0.00112, +0.00006], within noise |
| B + quick lineup + RAPM (`rp_b_plus_lu`) vs `lu_b` | 0.67378 | −0.00048 [−0.00102, +0.00008], within noise |
| Full logistic + projected lineup (`lu_logreg_full_C0.001`, reference) | 0.67224 | |
| Same + RAPM (`rp_logreg_full_C0.001`) | 0.67188 | −0.00036 [−0.00072, −0.00002], better |
| `rp_logreg_full_C0.001` vs Phase 3 logistic | | −0.00077 [−0.00138, −0.00018], better |
| Full + actual lineup + RAPM (`rp_logreg_full_actual_C0.001`) vs `lu_logreg_full_actual_C0.001` | 0.67170 | −0.00042 [−0.00080, −0.00006] |

The spec's adoption rule is met on dev: the paired interval against Baseline B excludes zero. The
adjusted ratings beat the quick version by about 0.0005 in both Baseline B and the full model. That
gain is within noise in Baseline B, but its interval excludes zero in the full model.

## Frozen for the test period

| Run | Config | Planned paired comparisons |
|---|---|---|
| `rp_b` | `configs/experiments/rapm/rp_b.yaml` | vs Baseline B (adoption rule), vs `lu_b` |
| `rp_logreg_full_C0.001` | `configs/experiments/rapm/rp_logreg_full_C0.001.yaml` | vs `lu_logreg_full_C0.001` (the live model), vs `p3_logreg_C0.001` |
| `rp_b_leaky` | `configs/experiments/rapm/rp_b_leaky.yaml` | upper bound only |
| `rp_logreg_full_actual_C0.001` | `configs/experiments/rapm/rp_logreg_full_actual_C0.001.yaml` | upper bound / the confirmed-lineup model |

Settings are `configs/features/base.yaml` `rapm: {lam: 300, halflife_months: 24}`. Nothing changes
after the test results. The live model switches to `rp_logreg_full_*` only if the test-period
comparison against `lu_logreg_full_C0.001` is not worse.

## Test results (2018-19 to 2025-26, n = 9,781), run once after the freeze

| Run | Test log loss | Paired vs reference |
|---|---|---|
| `rp_b` vs Baseline B | 0.66494 | −0.00138 [−0.00268, −0.00009], better |
| `rp_b` vs `lu_b` | | −0.00060 [−0.00135, +0.00009], within noise |
| `rp_b_leaky` vs Baseline B (upper bound) | 0.66424 | −0.00209 [−0.00350, −0.00069] |
| `rp_logreg_full_C0.001` vs `lu_logreg_full_C0.001` | 0.66433 | −0.00031 [−0.00070, +0.00007], within noise |
| `rp_logreg_full_C0.001` vs `p3_logreg_C0.001` | | −0.00067 [−0.00139, +0.00005], within noise |
| `rp_logreg_full_actual_C0.001` vs `lu_logreg_full_actual_C0.001` | 0.66375 | −0.00042 [−0.00084, −0.00001], better |

The adoption rule holds on test as well. Baseline B + RAPM clears Baseline B, which the quick lineup
features did not (−0.00079, within noise). Against the quick version, RAPM is better in both periods,
but by less than the noise on test. The frozen rule for the live model ("not worse") is met, so
`predict.py` now uses `rp_logreg_full_C0.001` and, once lineups are posted,
`rp_logreg_full_actual_C0.001`.

After the test run, the solver was switched from a direct sparse solve to conjugate gradient,
warm-started from the previous month. The ratings are unchanged (largest feature difference 2e-10)
and the feature build is back to ~1.6 min from ~5.5.
