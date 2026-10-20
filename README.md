# NHL moneyline model (research)

Predicts P(home team wins), overtime and shootout included, for NHL regular-season
games, and evaluates the predictions the way a bettor would need to: against the
de-vigged market, with time-ordered validation and confidence intervals.

**Analysis only.** Nothing here places, automates or recommends wagers.

## Status

| Phase | State |
|---|---|
| 0 Data discovery | done: [`docs/phase0_data_discovery.md`](docs/phase0_data_discovery.md) (live-verified) |
| 1 Dataset & features | mostly done: 16 seasons ingested; xG, goalie, team-strength, situational and score/venue-adjusted features (`docs/score_venue_choices.md`), lineup features from player on-ice xG (`docs/lineup_choices.md`). Remaining: teammate/opponent-adjusted player ratings (`docs/player_ratings_spec.md`), EDGE |
| 2 Baselines | done: see results below and `docs/eval_protocol.md` |
| 3 Model families | done: see results below and `docs/phase3_choices.md` |
| 4 Live predictions | done: `python -m nhlmodel.live`, scheduled GitHub Action, site on Vercel (see Live use and Hosting below) |
| 5 Betting-odds comparison | deferred: no odds data |

**Live use (current season).** One command, run once a day and again shortly before puck drop to pick up
posted lineups:

```bash
python -m nhlmodel.live      # update -> xG -> features -> predictions -> site/index.html
```

It runs these steps, which also work on their own:

```bash
python -m nhlmodel.ingest.cli update            # schedule, new games, goalie table, lineups posted within 2 h
python -m nhlmodel.xg.model --season 20262027   # xG for this season's shots (model trained on earlier seasons)
python -m nhlmodel.features.build               # features, including upcoming games
python -m nhlmodel.predict                      # P(home win) for each team's next game
```

**Hosting.** `.github/workflows/live.yml` runs `python -m nhlmodel.live` on GitHub Actions each morning and
hourly from 22:35 to 02:35 UTC (6 runs a day), then force-pushes the built page to the `site` branch. Vercel deploys
that branch: import the repo in Vercel (framework preset "Other", no build command), then set
Settings > Git > Production Branch to `site`. The root `vercel.json` turns off deployments for every other
branch. The predictions log (`predictions_log.csv`, the last prediction made before each game) is carried
between runs on the `site` branch and published with the page.

Things that can still change (the schedule, games final for under a day, the goalie table, posted
lineups) are stored as dated snapshots; per-game data becomes permanent once a game has been final for
24 h, so NHL stat corrections are picked up. Shift charts the NHL hasn't posted yet (48 early 2026-27
games so far) are retried on every update. Predictions use the full model with the projected lineup, or,
once both teams have posted a lineup, the same model trained with actual lineups.

## Outstanding items

Open work, in rough priority order:

1. **Check when lineups post.** The live workflow assumes teams post lineups at least ~30 minutes before
   puck drop: evening runs are hourly at :35 UTC, so each game gets one 25-55 minutes before it starts. Not yet
   seen live (none were posted 18 h before a game). If they post later, move the cron times in
   `.github/workflows/live.yml` or add runs.
2. **Teammate/opponent-adjusted player ratings** (RAPM), the full version of `docs/player_ratings_spec.md`.
   The quick version is in use; this should sharpen it. Special teams (PP/PK) would be a later step.
3. **EDGE features** (prior-season aggregates only; in-season EDGE can't be built without leakage).
4. **Betting-odds comparison (Phase 5).** Needs a historical odds source with usable terms. The loader and
   vig math are ready (`src/nhlmodel/odds/`).
5. **What-if calculator** on the site is still locked (needs the model's coefficients exported).
6. **Matinee games** (weekend/holiday afternoons) get only the 14:15 UTC prediction with expected lineups:
   no run catches their posted lineups. Add afternoon runs if that matters.
7. **Watch the extreme predictions.** Historically, games given under 25% were won 28% of the time
   (36 games): slightly overconfident. Check again as the live log grows.

Things to keep an eye on:

- **NHL data gaps.** Shift charts are empty upstream for 48 early 2026-27 games (2026020006-2026020053)
  and 57 games in 2024-25 (2024021235-2024021291). Current-season gaps are retried on every update. The NHL
  goalie table lags about a day, so a just-played game has no starter until it lands (the starter model
  covers it).
- **Scheduled runs stop after 60 days without repo activity** (GitHub rule for public repos). GitHub emails
  a warning; re-enable under Actions, or push any commit to `main`.
- **The live predictions log exists only on the `site` branch** (`predictions_log.csv`, carried between
  runs). Deleting or rewriting that branch by hand loses the live record.
- **Vercel's production branch must stay `site`** (Settings > Environments > Production > Branch Tracking).
- **`data` branch size:** `features.parquet` and `labels.parquet` are no longer stored there (rebuilt by
  `python -m nhlmodel.features.build`), so publishes stay small. Older copies remain in the branch history.

**Season rollover** (after the 2026-27 regular season ends): set `seasons.last` to 20262027 and
`seasons.current` to 20272028 in `configs/data.yaml`; run the full xG model (`python -m nhlmodel.xg.model`)
and rebuild features; publish the processed tables to the `data` branch. Until the `data` branch includes
the current season, each Actions run rebuilds it from the raw cache (re-downloaded in a few minutes if the
cache is evicted after 7 days unused).

## Results so far

Walk-forward, monthly refit, expanding window (protocol fixed in advance: `docs/eval_protocol.md`).
Log loss with 95% day-block bootstrap intervals; full table in `results/experiments.csv`.

| Model | Dev 2012-13 to 2017-18 (n=6,911) | Test 2018-19 to 2025-26 (n=9,781) |
|---|---|---|
| Baseline A: constant home win rate | 0.6887 [0.6863, 0.6911] | 0.6907 [0.6889, 0.6925] |
| Baseline B: logistic, xG share + goalie + rest + home | 0.6756 [0.6712, 0.6801] | 0.6663 [0.6621, 0.6706] |
| B with the *actual* starter (leaky upper bound) | 0.6758 | 0.6664 (within noise of B) |
| B with score-adjusted 5v5 xG share | 0.6755 | 0.6663 (within noise of B) |
| B + projected-lineup player features | 0.6743 | 0.6655 (within noise of B) |
| B + *actual* lineup (leaky upper bound) | 0.6741 | 0.6649 |
| Logistic, full matrix + projected lineup (C=0.001) | 0.6722 | **0.6647** [0.6598, 0.6694] |
| Logistic, full matrix + *actual* lineup (live model once lineups are posted) | 0.6721 | 0.6642 [0.6593, 0.6688] |
| Logistic regression, full 140-column matrix (C=0.001) | 0.6727 [0.6683, 0.6770] | **0.6650** [0.6602, 0.6696] |
| Random forest (leaf 200), same matrix | 0.6751 [0.6712, 0.6791] | 0.6671 [0.6628, 0.6714] |
| LightGBM (2-leaf trees), same matrix | 0.6747 [0.6704, 0.6790] | 0.6670 [0.6628, 0.6710] |

Phase 3 paired test differences: forest minus logistic +0.0021 [+0.0007, +0.0037] and LightGBM minus
logistic +0.0020 [+0.0004, +0.0035] (logistic better); logistic on 140 columns minus Baseline B on 5
features -0.0013 [-0.0035, +0.0007] (within noise). Calibration (Platt or isotonic on a held-out,
time-ordered set) made every family worse on dev and was not used.

Score adjustment of 5v5 xG (trailing teams shoot more) improved Baseline B on dev by -0.00015
[-0.00022, -0.00008], but on test only by -0.00007 [-0.00016, +0.00002] (within noise). Venue
adjustment added nothing on dev and was not carried to test. Both stay available as features.

Lineup features (player 5v5 on-ice xG from shift charts, summed over the expected lineup) improved
Baseline B on dev by -0.00134 [-0.00222, -0.00044]. On test the projected lineup (previous game's
skaters) gave -0.00079 [-0.00177, +0.00023] (within noise; better in 6 of 8 seasons). The actual
lineup gave -0.00145 [-0.00253, -0.00031]. Lineups are public about an hour before puck drop, so
live use could get close to that, but it can't be verified historically.

Rolling re-selection (`docs/rolling_check.md`): re-picking the model each season on all earlier
seasons chose the same model every time; re-picking on only the last 3 seasons was worse,
+0.00045 [+0.00009, +0.00082]. The settings chosen on the development seasons are kept.

The full model with the actual lineup beats the same model with the projected lineup on test by
-0.00047 [-0.00086, -0.00008] (dev: -0.00012, within noise). It is an upper bound for backtests, and the
live model once both teams post their lineups (about an hour before puck drop).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install -e . --no-deps
.venv/bin/pytest -q
```

Python 3.13. Exact versions are pinned in `requirements.lock`.

## Running

```bash
# Phase 1: ingestion (resumable; cached responses are never re-fetched)
python -m nhlmodel.ingest.cli schedule              # -> data/processed/games.parquet (~430 requests)
python -m nhlmodel.ingest.cli goalies               # goalie-games incl. starter flag (1 request/season)
python -m nhlmodel.ingest.cli games --what pbp &    # play-by-play, newest season first
python -m nhlmodel.ingest.cli games --what shifts   # shift charts (other host, so run in parallel)
python -m nhlmodel.ingest.process                   # -> data/processed/<table>/<season>.parquet
scripts/publish_processed.sh "msg"                  # push processed tables to the `data` branch
```

Each host is limited to 1 request/second, so the full backfill (~19k games × 2 documents)
takes ~5.3 h with both downloads running.

**Local front end** (swedish suede; shows only numbers read from files on disk):

```bash
python -m nhlmodel.report serve        # builds site/index.html, serves http://127.0.0.1:8000/
```

`site/index.html` is self-contained, so it can also be opened directly without the server. It plays like a
game menu: arrow keys / Enter / Esc (or mouse and touch). Areas without real results stay locked
and open themselves once those results exist. The text is written for readers without a statistics background. Settings has team color themes for all 32 NHL teams (they recolor the page, not the charts), light/dark, and an effects switch.

**Skip the download:** processed tables live on the `data` branch:

```bash
git fetch origin data
git archive origin/data processed | tar -x --strip-components=1 -C data/processed
python -m nhlmodel.features.build      # features.parquet + labels.parquet are not stored there (~1.5 min)
```

## Layout

```
configs/            YAML configs (data.yaml; experiment configs to follow)
data/raw/           immutable response cache + manifest.jsonl (gitignored)
data/processed/     derived tables, rebuildable from data/raw (gitignored)
src/nhlmodel/
  ingest/           cached HTTP client, NHL endpoints, schedule -> games table
  odds/             odds schema/loader, moneyline and vig math
  features/ xg/ models/ eval/ backtest/   (upcoming phases)
tests/              unit tests (leakage, vig math, calibration, ...)
results/            experiment log
docs/               findings and design notes
```

## Data lineage

- **Source:** unofficial NHL endpoints `api-web.nhle.com` and `api.nhle.com/stats/rest`
  (no official spec; schemas were verified live in Phase 0). Personal, non-commercial use only.
- **Raw:** each response is stored gzipped at `data/raw/<source>/<endpoint>/<key>.json.gz`,
  written once and never modified. 404s are stored as `.404` markers. Every network fetch
  is logged to `data/raw/manifest.jsonl` (URL, UTC time, status, sha256). Requests are
  spaced ≥1 s apart per host, with exponential backoff on 429/5xx.
- **Processed:** everything in `data/processed/` is a pure function of `data/raw/` plus code.

## Key decisions

- Regular season only, 2010-11 → 2025-26. 2010-11 is the first season with shot
  coordinates in play-by-play (verified).
- 2020-21 (mostly no fans, 56-game divisional season) is kept but flagged; evaluation is
  reported with and without it. 2012-13 and 2019-20 are flagged as shortened.
- Target `home_win` = home team's final score is higher, overtime and shootout included
  (standard NHL two-way moneyline settlement).
- Starting goalie: two variants are reported. *Projected* (pre-game info only, deployable)
  and *actual* (uses the post-game `starter` flag; leaky upper bound).
- Odds: free sources only. No free historical source has clean terms (see Phase 0 doc §3a),
  so the **market comparison (Baseline C, Phase 5) is deferred**. Models are judged on log
  loss, Brier score and calibration only. The loader (`src/nhlmodel/odds/loader.py`) and vig math
  stay in place for when an odds file the user may use becomes available.

## Known limitations

- Hockey is high-variance: the accuracy ceiling is roughly mid-50s to low-60s %, and
  beating the closing line is hard.
- NHL EDGE tracking data exists only from 2021-22 and only as season aggregates, so
  in-season EDGE features can't be built without leakage. Only prior-season aggregates are used.
- Confirmed-starter timing and injuries have no historical as-of source, so both are
  leakage risks; see the goalie variants above.
- No market benchmark yet: without odds we can't say whether the model beats the closing line,
  the question that matters most for betting.
- Backtests over a few seasons are noisy and may not generalize. A backtested edge is not
  a monetizable one: sportsbooks limit or close consistently winning accounts.
