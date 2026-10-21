# Spec: lineup-based team strength from player ratings

Status: done (5v5 v1). Choices, deviations and results: `docs/player_ratings_choices.md`.

## Why

Current team features are windowed averages of a team's own past results. They react slowly to
injuries, trades and call-ups, and they don't separate a team from the players who were on the ice.
Rating players and adding up the ratings of the expected lineup gives the model information it does
not have now.

## Data already on hand (checked 2026-10-20)

| Table | What it gives | Coverage |
|---|---|---|
| `shifts` | player, team, period, start/end seconds | every season; `shifts_ok` ≥ 0.995 except 2024-25 (0.957) |
| `events` | `situation_code`, period time, event team | every season |
| `xg` | xG per unblocked shot, by `event_id` | 2011-12 on |
| `rosters` | the 20 players dressed per team-game, with position | every game |
| `skater_toi` | TOI per player-game | from shifts |

Known gap: 57 consecutive 2024-25 games (game ids 2024021235 to 2024021291) have empty shift charts.
Ratings simply get no update from those games. Lineups still come from `rosters`, so features for
games after them are unaffected beyond that.

No new downloads are needed.

## Design

### 1. Stints (`src/nhlmodel/ratings/stints.py`)

Cut each game into stints: intervals where the set of skaters and goalies on ice doesn't change.
Each stint row holds game_id, start/end game-seconds, duration, home and away skater ids, strength
state, score state, home xG, away xG, and whether it started with a faceoff in either end.

- Keep 5v5 with both goalies in for the first version (situation code 1551, about 80% of events).
- Shot events at a shift boundary go to the stint that ends at that second. This is the usual
  convention for NHL shift data; a unit test pins it down.
- Validation, as an integrity check like `quality`: per game, summed stint xG within 1% of the `xg`
  table's 5v5 total, and summed stint seconds within 2% of 5v5 time from events. Games that fail are
  listed and excluded.

### 2. Ratings (`src/nhlmodel/ratings/rapm.py`)

Regularized adjusted plus-minus (RAPM) on xG:

- One row per stint and direction (home attacking, away attacking). Target is xG per 60, weighted by
  stint duration.
- Columns: attacking skaters (+1), defending skaters (+1, separate coefficients), home indicator,
  score state of the attacking team (trailing / tied / leading), offensive-zone faceoff start. This
  gives each player an offensive and a defensive rating.
- Ridge penalty toward a prior instead of toward zero. The prior is the player's rating as of the
  previous fit, regressed toward the mean by a factor tuned on dev. Players with no history start at
  the mean for their position. This lets the ratings carry over across seasons without reusing old
  data unshrunk.
- As-of rule (same as walk-forward): ratings used for any game in month M are fit only on stints
  from games that started before the first day of M. One fit per month boundary, about 115 fits
  over 2010-11 to 2025-26.
- Output `data/processed/player_ratings.parquet`: player_id, asof_date, off, def, stint seconds seen.
- Tuning on dev only: ridge penalty (λ), prior carry-over (0 to 1), and the length of the rolling
  window if the full history turns out worse than recent seasons (3 or 5 seasons).

### 3. Expected lineup (`src/nhlmodel/features/lineups.py`)

Two variants, the same pattern as goalies:

- **Projected (deployable):** the skaters who dressed in the team's previous game.
- **Actual (`leaky_` prefix, upper bound):** the game's own roster. Lineups are public about an hour
  before puck drop, but there is no historical as-of source, so this is reported, never selected on.

Each skater gets an expected-TOI weight from an exponentially weighted average of their 5v5 TOI in
earlier games, normalized to 5 skaters × 60 minutes per team.

### 4. Team features (added in `features/build.py`)

Per team, then home minus away like the other features:

- `lineup_off`, `lineup_def`, `lineup_net`: TOI-weighted sums of the lineup's ratings.
- `lineup_turnover`: the TOI-weighted share of the team's last-10-game regulars missing from the
  lineup (a signal of injuries and call-ups).

### 5. Experiments (dev 2012-13 to 2017-18 only, until frozen)

1. Baseline B + `lineup_*` (projected), grid over λ and prior carry-over.
2. Ablation: lineup features alone + rest + home (do they replace xG share or add to it?).
3. The Phase 3 logistic regression matrix + lineup features.
4. The leaky actual-lineup variant alongside, as an upper bound.

Choices are written to `docs/player_ratings_choices.md` and committed before any test-period run.
Then a single test run, with paired differences against Baseline B and against the Phase 3
logistic. **Adopted only if the paired dev interval against Baseline B excludes zero**; otherwise it
is reported as a negative result, like calibration was.

### 6. Tests

- Stints: boundary assignment, penalties and pulled goalies ending 5v5, overlapping shifts.
- Leakage: a rating used for a game never includes a stint from that game or later (property test
  over random games, like the existing as-of tests).
- Lineups: the projected variant never reads the current game's roster.
- Validation totals reproduce the `xg` table for a few fixture games.

## Effort and ETA

My working-time estimates, assuming no surprises in the shift data:

| Step | Work | Compute |
|---|---|---|
| Stints + validation + tests | ~0.5 day | ~20 min for 16 seasons |
| RAPM with prior, as-of fits + leakage tests | ~1 day | ~1 h for all monthly fits (sparse ridge) |
| Lineups + team features | ~0.5 day | minutes |
| Dev experiments, freeze doc, test run, README | ~0.5–1 day | ~1 h |
| **Total** | **~2.5–3 days** | **~2–3 h** |

The score and venue adjustment (~0.5 day) goes first, so the ETA for both is about 3–3.5 days of
work. The calendar time depends mainly on review points: one after the stint validation, and one at
the freeze before the test run.

## Risks

- **Expected gain is small and may be within noise.** Public models built on player ratings usually
  beat team-level models by little in hockey. The pre-stated adoption rule above keeps that honest.
- RAPM is noisy for players with little ice time. The prior and TOI weighting limit the damage;
  depth players contribute little to the lineup sum.
- Coaching changes and line combinations aren't modeled.
- Special teams (PP/PK) are left out of v1. They are a possible v2 if v1 shows a gain.
