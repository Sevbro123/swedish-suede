# NHL moneyline model (research)

Predicts P(home team wins), overtime and shootout included, for NHL regular-season
games, and evaluates the predictions the way a bettor would need to: against the
de-vigged market, with time-ordered validation and confidence intervals.

**Analysis only.** Nothing here places, automates or recommends wagers.

## Status

| Phase | State |
|---|---|
| 0 Data discovery | done: [`docs/phase0_data_discovery.md`](docs/phase0_data_discovery.md) (live-verified) |
| 1 Dataset & features | in progress: cached ingestion, games table, odds loader and vig math done |
| 2–5 | not started |

**To do (before live/forward use):** an `update` command for the current season. It
fetches the schedule uncached, downloads per-game data only for games that went final
at least a day earlier (to pick up NHL stat corrections), caches those, and appends them
to the processed tables.

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
python -m nhlmodel.ingest.cli schedule                         # -> data/processed/games.parquet
python -m nhlmodel.ingest.cli games --what pbp boxscore shifts # raw per-game JSON
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
- Odds: free sources only. The loader schema is documented in `src/nhlmodel/odds/loader.py`.
  Vig removal: multiplicative by default, power method available.

## Known limitations

- Hockey is high-variance: the accuracy ceiling is roughly mid-50s to low-60s %, and
  beating the closing line is hard.
- NHL EDGE tracking data exists only from 2021-22 and only as season aggregates, so
  in-season EDGE features can't be built without leakage. Only prior-season aggregates are used.
- Confirmed-starter timing and injuries have no historical as-of source, so both are
  leakage risks; see the goalie variants above.
- Free historical odds are expected to end around 2022-23 and lack timestamps.
- Backtests over a few seasons are noisy and may not generalize. A backtested edge is not
  a monetizable one: sportsbooks limit or close consistently winning accounts.
