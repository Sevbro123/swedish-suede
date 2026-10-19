# Phase 3: choices frozen on development seasons

Written and committed before any Phase 3 test-period result was produced.

All runs: walk-forward, monthly refit, expanding window from 2011-12; development seasons
2012-13 to 2017-18 (n = 6,911 games); identical full design matrix (137 home-minus-away
differences + 3 context columns). Log loss with 95% day-block bootstrap intervals.

## Tuning grids (uncalibrated)

| Family | Setting | Dev log loss |
|---|---|---|
| Logistic regression | C = 0.1 | 0.68331 |
| | C = 0.01 | 0.67627 |
| | **C = 0.001** | **0.67265** |
| | C = 0.0003 | 0.67303 |
| | C = 0.0001 | 0.67464 |
| Random forest (500 trees) | leaf 50, sqrt features | 0.67589 |
| | leaf 100, 30% features | 0.67544 |
| | **leaf 200, sqrt features** | **0.67508** |
| | leaf 400, sqrt features | 0.67604 |
| LightGBM (lr 0.02) | 15 leaves, 300 rounds | 0.67925 |
| | 7 leaves, 300 rounds | 0.67782 |
| | 7 leaves, lr 0.01, 600 rounds | 0.67794 |
| | 7 leaves, 150 rounds | 0.67586 |
| | 7 leaves, 300 rounds, min leaf 500 | 0.67540 |
| | 3 leaves, 300 rounds | 0.67529 |
| | **2 leaves (stumps), 300 rounds** | **0.67467** |

Every family preferred its most constrained setting; the grids were extended until the best
setting was interior (logistic, forest) or at the structural floor (2-leaf trees). LightGBM
improving all the way down to stumps means the best tree model is an additive one: the signal
in these features is close to additive.

## Calibration round (best setting per family)

Calibrator fit on the most recent games before each refit (1,500, capped at 20% of the pool),
which the base model never trains on; split at a start-time boundary.

| Family | Platt minus none | Isotonic minus none |
|---|---|---|
| Logistic | +0.00237 [+0.00113, +0.00352] | +0.01779 [+0.01044, +0.02647] |
| Random forest | +0.00105 [+0.00015, +0.00193] | +0.01623 [+0.00796, +0.02526] |
| LightGBM | +0.00161 [+0.00025, +0.00296] | +0.01821 [+0.00925, +0.02736] |

Calibration hurt every family. The uncalibrated models already had low calibration error
(0.012 to 0.019); holding out the most recent games costs the base model its most relevant
data; isotonic overfits small early calibration sets.

## Frozen for the test period

| Family | Config | Calibration |
|---|---|---|
| Logistic regression | `p3_logreg_C0.001` | none |
| Random forest | `p3_rf_leaf200_sqrt` | none |
| LightGBM | `p3_lgbm_l2_lr0.02_n300` | none |

Test-period comparisons planned: each family vs logistic regression (paired), and each vs
Baseline B (paired). No further changes after test results.
