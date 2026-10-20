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
| 4–5 | not started (5 deferred: no odds data) |

**To do (before live/forward use):** an `update` command for the current season. It
fetches the schedule uncached, downloads per-game data only for games that went final
at least a day earlier (to pick up NHL stat corrections), caches those, and appends them
to the processed tables.

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
and open themselves once those results exist; Settings has the light theme and an effects switch.

**Skip the download:** processed tables live on the `data` branch:

```bash
git fetch origin data
git archive origin/data processed | tar -x --strip-components=1 -C data/processed
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
