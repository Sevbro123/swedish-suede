# NHL moneyline model (research)

Predicts P(home team wins), overtime and shootout included, for NHL regular-season
games, and evaluates the predictions the way a bettor would need to: against the
de-vigged market, with time-ordered validation and confidence intervals.

**Analysis only.** Nothing here places, automates or recommends wagers.

## Status

| Phase | State |
|---|---|
| 0 Data discovery | done: [`docs/phase0_data_discovery.md`](docs/phase0_data_discovery.md) (live-verified) |
| 1 Dataset & features | mostly done: 16 seasons ingested; xG, goalie, team-strength, situational and score/venue-adjusted features (`docs/score_venue_choices.md`), lineup features from player on-ice xG (`docs/lineup_choices.md`), teammate/opponent-adjusted player ratings (RAPM, `docs/player_ratings_choices.md`), Elo results rating (`docs/elo_choices.md`). Remaining: EDGE |
| 2 Baselines | done: see results below and `docs/eval_protocol.md` |
| 3 Model families | done: see results below and `docs/phase3_choices.md` |
| 4 Live predictions | done: `python -m nhlmodel.live`, scheduled GitHub Action, site on Vercel (see Live use and Hosting below) |
| 5 Betting-odds comparison | historical comparison deferred (no odds data); paper trading forward from 2026-10-22 (see Paper trading below) |

**Live use (current season).** One command, run once a day and again in the last minutes before puck drop to
pick up posted lineups (they post 5-15 min before it: `docs/lineup_timing.md`):

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

**Hosting.** `.github/workflows/live.yml` runs `python -m nhlmodel.watch` on GitHub Actions: it runs
`nhlmodel.live` and force-pushes the built page to the `site` branch (`scripts/publish_site.sh`), then stays up
while games are due, polling the lineups of games starting within 25 minutes every minute and republishing as
soon as one posts. A run stays up only while a game starts within 90 minutes, and at most 3 h. Triggers come
every 30 minutes from 13:07 to 03:37 UTC, and ones that arrive while a run is going wait as a single pending run, so late or dropped GitHub schedules don't leave gaps
(`docs/lineup_timing.md`). Vercel deploys
that branch: import the repo in Vercel (framework preset "Other", no build command), then set
Settings > Git > Production Branch to `site`. The root `vercel.json` turns off deployments for every other
branch. The predictions log (`predictions_log.csv`, the last prediction made before each game) is carried
between runs on the `site` branch and published with the page.

Things that can still change (the schedule, games final for under a day, the goalie table, posted
lineups) are stored as dated snapshots; per-game data becomes permanent once a game has been final for
24 h, so NHL stat corrections are picked up. Shift charts the NHL hasn't posted yet (48 early 2026-27
games so far) are retried on every update. Predictions use the full model with the projected lineup, its
adjusted player ratings and both teams' Elo rating (`el_logreg_full_C0.001`), or, once both teams have posted a lineup, the same model
trained with actual lineups. Each prediction is also split into per-stat terms (`explain_upcoming.parquet`;
the model is a standardized logistic regression, so the split is exact), and each upcoming-game card on the
site opens a page showing what pushes it toward either team.

**Front end.** The page is a React app in `web/` (Vite, Tailwind, [motion](https://motion.dev) for
transitions, charts from [bklit-ui](https://github.com/bklit/bklit-ui) vendored in `web/src/bklit/`, MIT).
`cd web && npm install && npm run build` bundles it into one self-contained HTML file and copies it over
`src/nhlmodel/report/template.html`, which is committed, so the live workflow needs no Node: `report/build.py`
only swaps the data placeholder for the payload. For `npm run dev`, save a payload as
`web/public/dev-payload.json` (the JSON inside `<script id="payload">` of a built page).

## Progress log

Where things stand as of 2026-10-24, so work can pick up from here.

- **2026-10-19:** Phases 0-3 done. Logistic regression on the full feature matrix with strong shrinkage
  (C=0.001) beat random forest and LightGBM on the test period; calibration didn't help.
- **2026-10-20:** score/venue-adjusted 5v5 stats, lineup features from player on-ice xG, rolling
  re-selection check (keep the dev-chosen settings), current-season updates with live predictions, the
  Vercel site, and confirmed lineups. `features.parquet` and `labels.parquet` stopped being stored on the
  `data` branch; every live run rebuilds them.
- **2026-10-21, PR #1:** each upcoming-game card on the site opens a page explaining its prediction (exact
  per-stat split of the logistic model, `explain_upcoming.parquet`).
- **2026-10-21, PR #2:** adjusted player ratings (5v5 RAPM on xG from shift-chart stints,
  `src/nhlmodel/ratings/`, `docs/player_ratings_choices.md`). Settings frozen on dev: λ = 300 minutes,
  24-month half-life. Baseline B + RAPM beat Baseline B on test, so the live model switched to the full model
  + RAPM (`rp_logreg_full` configs). Stints aren't on the `data` branch, so each Actions run rebuilds them
  (about 1.5 min). Special-teams (PP/PK) ratings are the planned v2.
- **2026-10-21, PR #3:** the live workflow became a lineup watcher (`python -m nhlmodel.watch`) instead of
  fixed run times. GitHub's cron started runs hours late or dropped them, and dressed lineups post only
  5-15 minutes before puck drop (`docs/lineup_timing.md`).

- **2026-10-21, PR #7:** paper trading on the NHL partner book's moneylines (`src/nhlmodel/paper.py`,
  `configs/paper.yaml`, odds log carried on the `site` branch, new Paper bets page). See Paper trading below.
- **2026-10-22, PR #9:** paper stakes scale with the edge (1u/2u/3u at 3/5/8 points), a flat 1u benchmark is
  kept beside it, and a daily 0.5u parlay of the strongest 2-3 picks (`paper_parlays.csv`).
- **2026-10-22, PR #10:** the odds log keeps a fresh row at least every 25 minutes even when the price
  hasn't moved. Before, unchanged prices were skipped, bets failed the price-freshness rule and Oct 22 had
  no bets.
- **2026-10-22:** recent-form ("hot streak") features for skaters, starters and teams
  (`src/nhlmodel/features/form.py`, `docs/form_choices.md`). Goal-scoring and goalie streaks barely carry
  over (slope 0.02-0.06 into the next games); no form feature beat the current model on dev or test, so
  the live model is unchanged.
- **2026-10-23:** audit of missing inputs. Four candidates were added to the live model with settings fixed
  in advance: travel distance and road-trip length, each team's own home/road split, and the projected
  starter's rest all stayed within noise. An Elo results rating (`src/nhlmodel/features/elo.py`,
  `docs/elo_choices.md`) beat the live model on dev and test, so the live model switched to the full model +
  RAPM + Elo (`el_logreg_full` configs). Merged as PR #11 on 2026-10-24.
- **2026-10-24, PR #12:** front end rebuilt as a React app in `web/` (Apple-style design, bklit-ui charts,
  motion transitions; see Front end above), replacing the game-menu page. The Shot Quality, The Data and
  What-if Calculator sections had been dropped on 2026-10-21. Pages now: Overview, Upcoming, Paper bets,
  Models, Game log, plus a Settings sheet. The Overview page has a reader-facing What's new list
  (`NEWS` in `web/src/pages/Overview.tsx`); add a line there when something visible changes.
- **2026-10-24, PRs #12-13:** repo skills for Claude sessions in `.claude/skills/`: `ponytail`
  (token-saving rules), `apple-design` and `emil-design-eng` (front-end design and animation guidance).

## Outstanding items

Done since the last list: 5v5 player ratings (PR #2), the lineup watcher that replaced fixed run times
(PR #3), forward paper trading (PRs #7, #9, #10), the Elo rating (PR #11) and the new front end (PR #12). Open work, in rough priority order:

1. **Lineups that post after puck drop.** Checked live on 2026-10-20 (`docs/lineup_timing.md`): dressed
   lineups land in rosterSpots 5-15 minutes before puck drop, and for 4 of 11 games only after it. The watcher
   catches the first kind; for the second, look for an NHL source that posts earlier. Tally a few more nights
   from the run logs (`lineup ...: confirmed (20/20)` lines) first.
2. **Special-teams player ratings** (PP/PK), the v2 of the 5v5 RAPM ratings now in use
   (`docs/player_ratings_choices.md`).
3. **EDGE features** (prior-season aggregates only; in-season EDGE can't be built without leakage).
4. **Betting-odds comparison (Phase 5).** Needs a historical odds source with usable terms. The loader and
   vig math are ready (`src/nhlmodel/odds/`). Going forward, paper trading records prices instead.
5. **Actions minutes.** The watcher keeps a runner up from about 90 minutes before the first puck drop to the
   last one (about 4-6 hours on a full night), plus about 3 minutes per idle trigger. Free for a public repo;
   on a private one it would exceed the free tier.
6. **Watch the extreme predictions.** Historically, games given under 25% were won 28% of the time
   (36 games): slightly overconfident. Check again as the live log grows.

**Paper trading.** Each live run, and each minute the watcher polls games about to start, reads the NHL
betting partner's current 2-way moneylines (`/v1/partner-game/US/now`, no key needed) into
`data/processed/odds_log.csv`, which travels between runs on the `site` branch like the predictions log
(so it is readable at the site's URL). `nhlmodel.paper` rebuilds the bets from the two logs every run: each
game's last prediction before puck drop, at the price read in that same run, bets a side whose model
chance beats the no-vig price by 3+ points (closer is a toss-up: no bet). The stake grows with the edge
(1 unit at 3-5 points, 2 at 5-8, 3 at 8+), and a flat 1u version of the same bets is kept as a benchmark.
Goal: grow the 100u bankroll to 10,000u. Each day one unit is worth 1% of the bankroll after earlier days'
settled bets and parlays (rounded down to 0.25u, never below 1u; no bet over 4% of the bankroll), roughly a
fifth to a quarter of full Kelly, so stakes rise past 1u as the bankroll grows and shrink after losses.
When 2+ games on a day clear 5 points, the strongest (up to 3) also go into a 0.5u parlay, kept in
`paper_parlays.csv` (carried on the `site` branch) and locked once its first game starts. The last price
before puck drop is the close (for CLV). Rules are in `configs/paper.yaml`; the site's Paper bets page
shows both bankrolls, record, ROI, CLV, every bet and every parlay.

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
| Logistic, full matrix + projected lineup (C=0.001) | 0.6722 | 0.6647 [0.6598, 0.6694] |
| Logistic, full matrix + *actual* lineup | 0.6721 | 0.6642 [0.6593, 0.6688] |
| B + projected lineup's adjusted player ratings (RAPM) | 0.6737 | 0.6649 [0.6603, 0.6696] |
| B + *actual* lineup's RAPM (leaky upper bound) | 0.6734 | 0.6642 |
| Logistic, full matrix + projected lineup + RAPM (C=0.001) | 0.6719 | 0.6643 [0.6595, 0.6692] |
| Logistic, full matrix + *actual* lineup + RAPM | 0.6717 | 0.6638 [0.6588, 0.6686] |
| Logistic, full matrix + projected lineup + RAPM + Elo (C=0.001), **live model** | 0.6716 | **0.6638** [0.6588, 0.6688] |
| Logistic, full matrix + *actual* lineup + RAPM + Elo (live model once lineups are posted) | 0.6714 | 0.6632 [0.6583, 0.6681] |
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

Adjusted player ratings (`docs/player_ratings_choices.md`): ridge RAPM on 5v5 xG from shift-chart
stints, an offense and a defense rating per player, refit monthly, summed over the expected lineup. The
two settings (penalty, decay of older seasons) were chosen on dev. On test, Baseline B + RAPM beats
Baseline B by -0.00138 [-0.00268, -0.00009], the first projected-lineup feature to clear Baseline B on
test, so the spec's adoption rule holds. Against the quick lineup features it is -0.00060 [-0.00135,
+0.00009] in Baseline B and -0.00031 [-0.00070, +0.00007] in the full model (both within noise, better in
both periods). The live model switched to the full model + RAPM, as the frozen rule allowed.

Elo results rating (`docs/elo_choices.md`): each team's Elo from the wins and goal margins of its earlier
games, settings fixed in advance. Added to the live model it gives -0.00026 [-0.00049, -0.00005] on dev and
-0.00055 [-0.00084, -0.00026] on test (actual-lineup version: -0.00026 dev, -0.00053 [-0.00081, -0.00024]
test), the largest single gain since lineups. The live model switched to the `el_logreg_full` configs.

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

`site/index.html` is self-contained, so it can also be opened directly without the server. Sections:
Overview (with a What's new list), Upcoming (each game opens a page explaining its prediction), Paper bets,
Models and Game log; on
a phone they sit in a bottom tab bar. The text is written for readers without a statistics background.
Settings has light/dark/auto, full or reduced motion, and team accent colors for all 32 NHL teams. To change
the page itself, edit `web/` and rebuild (see Front end above).

**Skip the download:** processed tables live on the `data` branch:

```bash
git fetch origin data
git archive origin/data processed | tar -x --strip-components=1 -C data/processed
python -m nhlmodel.features.build      # features.parquet + labels.parquet are not stored there (~1.5 min)
```

## Layout

```
configs/            YAML configs (data.yaml, paper.yaml, experiment configs)
data/raw/           immutable response cache + manifest.jsonl (gitignored)
data/processed/     derived tables, rebuildable from data/raw (gitignored)
src/nhlmodel/
  ingest/           cached HTTP client, NHL endpoints, schedule -> games table
  odds/             odds schema/loader, moneyline and vig math, NHL partner-book prices
  paper.py          paper trading: bets rebuilt from the predictions and odds logs, graded
  ratings/          5v5 stints and RAPM player ratings
  report/           site payload builder; template.html is the built web/ app
  features/ xg/ models/ eval/ backtest/   features (incl. Elo, form), xG model, model families, evaluation
  live.py watch.py predict.py             live run, lineup watcher, predictions
web/                React front end (Vite, Tailwind, motion, bklit-ui charts)
.claude/skills/     repo skills for Claude sessions (ponytail, apple-design, emil-design-eng)
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
- No historical market benchmark: without past odds we can't say whether the model beat the closing line,
  the question that matters most for betting. Paper trading measures it going forward, but that sample is
  still small.
- Backtests over a few seasons are noisy and may not generalize. A backtested edge is not
  a monetizable one: sportsbooks limit or close consistently winning accounts.
