# Recent form ("hot streaks"): findings

Question (2026-10-21): can the model credit skaters who have been producing well above their norm lately,
or a goalie in great form? Short answer: we built and tested it, and on 14 seasons of games it adds
nothing measurable on top of what the model already uses. The live model is unchanged.

## How the model already learns from results

There is no explicit "learn from my mistakes" loop, and that is deliberate. Results reach the model in
two ways:

- **Refits.** Every live run retrains the logistic regression on every completed game, so yesterday's
  results move the weights. In backtests the refit is monthly.
- **Inputs that update after every game.** Team shot and xG stats over the last 5, 10 and 20 games,
  exponentially weighted ones (half-life 5 and 15 games) and season-to-date; the starter's goals saved
  above expected (GSAx, recent games weighted with a 20-game half-life); each skater's on-ice xG (40-game
  half-life). Adjusted player ratings (RAPM) are refit at each month boundary with a 24-month half-life.

Feeding the model its own past errors would mostly teach it noise: one game's result is mostly luck.

## What was added

`src/nhlmodel/features/form.py`, all "recent minus own norm", so it measures a heater on top of talent:

- **Skaters** (summed over the lineup): points, goals and own-shot xG per game over the last 5 / 10 / 20
  games minus the player's long-run rate (82-game half-life, shrunk toward the F or D league rate).
- **Goalies:** GSAx per 100 shots over the expected starter's last 3 / 5 / 10 appearances minus his career
  rate. `leaky_` = the actual starter (upper bound).
- **Team:** win rate over the last 5 / 10 / 20 games and the current win or loss streak.

`configs/features/base.yaml` `form:` holds the settings (fixed in advance, not tuned). The full matrix
leaves `form_*` out unless a config sets `features: full_rapm_form`. Tests: `tests/test_form.py`.

## Do streaks carry over at all?

`scripts/form_persistence.py` (`results/form_persistence.csv`) regresses the next stretch above a
player's norm on the last stretch. Slope 0 = pure noise, 1 = the streak carries over in full.

| Who | Stat | Last 5 | Last 10 | Last 20 |
|---|---|---|---|---|
| Skater (next 10 games) | goals | 0.02 | 0.03 | 0.06 |
| Skater | points | 0.07 | 0.12 | 0.21 |
| Skater | own-shot xG | 0.14 | 0.23 | 0.35 |

Goalies (GSAx/100 over the next 5 appearances): 0.01 from the last 3 appearances, 0.02 from the last 5,
0.04 from the last 10.

A skater scoring a goal a game above his norm over 5 games scores about 0.02 a game above it over the
next 10: goal streaks are almost pure luck. Goalie hot streaks carry over even less. Getting more
chances (own-shot xG) does persist, about a third of a 20-game surge, likely from changes in role,
linemates or ice time. That part is real, but the lineup and team xG features already see most of it.

## Model tests (walk-forward, paired day-block bootstrap, protocol in `eval_protocol.md`)

Reference on dev: Baseline B + RAPM (`rp_b`, 0.67373, reproduced exactly after the rebuild).

| Dev run (2012-13 to 2017-18, n = 6,911) | vs `rp_b` |
|---|---|
| + skater form, last 5 | +0.00013 [-0.00026, +0.00054] |
| + skater form, last 10 | +0.00023 [-0.00022, +0.00070] |
| + skater form, last 20 | -0.00032 [-0.00086, +0.00019] |
| + starter form, last 3 | -0.00010 [-0.00060, +0.00040] |
| + starter form, last 5 | -0.00002 [-0.00063, +0.00057] |
| + starter form, last 10 | +0.00024 [-0.00020, +0.00065] |
| + team wins last 5 + streak | +0.00009 [-0.00015, +0.00033] |
| + team wins last 10 + streak | -0.00013 [-0.00066, +0.00046] |
| + ACTUAL lineup's skater form, last 10 (upper bound) | -0.00009 [-0.00061, +0.00044] |
| + ACTUAL starter's form, last 5 (upper bound) | +0.00036 [-0.00026, +0.00097] |
| + best window of each (`fm_b_all`) | -0.00043 [-0.00127, +0.00045] |
| Live model + those form columns (`fm_logreg_full_C0.001`) vs live model | +0.00013 [-0.00008, +0.00036] |

Every result is within noise; none meets the adoption rule (paired interval below zero). Even the actual
starter's form, which uses information we wouldn't have before the game, doesn't help.

The two combined configs were written from the dev results above before any test run, then run once:

| Test run (2018-19 to 2025-26, n = 9,781) | Log loss | vs reference |
|---|---|---|
| `fm_b_all` vs `rp_b` | 0.66531 | +0.00037 [-0.00033, +0.00105], within noise |
| `fm_logreg_full_C0.001` vs live `rp_logreg_full_C0.001` | 0.66445 | +0.00012 [-0.00011, +0.00033], within noise |

## Decision

Not adopted. Recent form is mostly noise for goals and goalie saves, and its real part (players getting
more chances) is already in the model through recent team xG, recent goalie GSAx and lineup ratings.
The features stay in the code and the feature table so this can be re-checked as the data grows.
