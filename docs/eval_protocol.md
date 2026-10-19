# Evaluation protocol (fixed before any model is fit)

## Periods

| Period | Seasons | Used for |
|---|---|---|
| Burn-in | 2010-11 | Features only (xG needs an earlier season). Never evaluated. |
| Training-only | 2011-12 | First season with xG features; only ever in training sets. |
| **Development** | 2012-13 to 2017-18 | Every modeling choice: feature sets, regularization, windows, model families, calibration method. |
| **Test** | 2018-19 to 2025-26 | Reported only. Choices are frozen before test results are looked at. |

Reasons: development needs at least one training season with xG behind it; the test period
covers eight seasons, including the drift seen in xG from 2019-20 on, and the 2020-21
no-fans season.

## Walk-forward, expanding window

- For every month in an evaluated season, the model is refit on **all games that started
  before the first day of that month** (all earlier seasons plus earlier months of the
  current season), then predicts that month's games. Never a random split.
- A model never sees any game on or after the first game it predicts.
- Features are built as-of each game's start (see `features/asof.py`), independent of the
  refit schedule.

## Metrics, always tagged with their split

- **Primary:** log loss. **Also:** Brier score, expected calibration error (10 equal-count
  bins), calibration curve. Accuracy is reported but never used to pick models.
- **Uncertainty:** block bootstrap over **game days** (all games on one date resampled
  together, since same-day games share league conditions), 2,000 resamples, 95% percentile
  intervals. Model comparisons use **paired** bootstraps of the per-game metric difference
  on the same resamples. A difference whose interval includes 0 is reported as "within noise".
- Each run is reported overall, by season, and **with and without 2020-21** (no fans).
  Neutral-site games stay in, with a neutral-site indicator.

## Goalie variants

Every model that uses goalie features is reported with the **expected** (pre-game starter
model, deployable) variant. The **leaky** actual-starter variant is reported alongside as an
upper bound and is never used to select anything.

## Experiment log

Every run appends one row to `results/experiments.csv`: run id, date, git revision, config,
feature groups, window config, model, hyperparameters, split (period + seasons), n games,
log loss with 95% CI, Brier, ECE, accuracy.
