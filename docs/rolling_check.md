# Rolling re-selection check

Question: does re-picking the model each season, using the most recent seasons, beat picking it
once on the development seasons (2012-13 to 2017-18)?

## Setup (fixed before running: `configs/experiments/rolling.yaml`)

- 18 logistic candidates: simple model and simple + expected lineup (C = 0.001, 0.01, 0.1, 1),
  full matrix and full matrix + expected lineup (C = 0.0001, 0.0003, 0.001, 0.003, 0.01).
- Each candidate runs once, walk-forward with monthly refits, over 2012-13 to 2025-26.
- For each test season S, a rule picks the candidate with the lowest log loss on seasons before S:
  - **expanding**: all seasons from 2012-13 to S-1
  - **last3**: the three seasons before S
- **fixed**: picked once on 2012-13 to 2017-18, never changed.
- Paired day-block bootstrap over the 9,781 test games (`python -m nhlmodel.eval.rolling`).

## Results (test seasons 2018-19 to 2025-26)

| Rule | Log loss | Paired vs fixed |
|---|---|---|
| fixed (`full_lineup_C0.001` every season) | 0.66465 | |
| expanding | 0.66465 | +0.00000 (same pick every season) |
| last3 | 0.66509 | +0.00045 [+0.00009, +0.00082], worse |

Picks: the expanding rule chose `full_lineup_C0.001` in every season. The last-3 rule switched
to C = 0.0003 for 2021-22 and to C = 0.003 for 2023-24 to 2025-26. It gained in 2024-25 (-0.0008)
and lost in 2021-22 (+0.0020), 2023-24 (+0.0004) and 2025-26 (+0.0016).

In hindsight, the fixed pick is also the best single candidate over the whole test period
(0.66465; next best 0.66495).

## Reading

- Re-picking on all available history changes nothing: the development-season choice keeps
  winning as seasons are added.
- Re-picking on recent seasons only is reliably worse. Three seasons (about 3,900 games) are too few
  to choose between settings whose differences are about 0.0003, so the rule mostly chases noise.
- The model does adapt to recent hockey: every candidate retrains monthly on all earlier games.
  What doesn't need refreshing is the choice of settings.
- Decision: keep the settings chosen on the development seasons. For live use, retrain on all
  games through yesterday, as the walk-forward already does.
