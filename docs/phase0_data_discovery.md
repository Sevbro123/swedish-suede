# Phase 0 — Data discovery findings

Date: 2026-10-18. Sections 1–3 were written from documentation while the NHL
hosts were blocked. Network access was then granted and the claims were tested;
**section V (below) supersedes them wherever they differ.**

## V. Verification results (live, 2026-10-18)

One sample per endpoint, ~1 req/s. Games used: 2023020204 (MIN–BUF, 2023-11-10),
2010020100, 2008020100; team 10 (TOR); skater 8478483; goalie 8475883.

| Claim | Result |
|---|---|
| `api-web` schedule (`/schedule/{date}`, `/club-schedule-season/{team}/{season}`) | **VERIFIED.** Has `id`, `gameType`, `gameDate`, `startTimeUTC`, `venueUTCOffset`, `venueTimezone`, `neutralSite`, `homeTeam/awayTeam.{id,abbrev,score}`, `gameOutcome.lastPeriodType` (REG/OT/SO) |
| Boxscore | **VERIFIED.** `playerByGameStats.{homeTeam,awayTeam}.{forwards,defense,goalies}`; goalie rows have `starter: bool`, `toi`, `shotsAgainst`, `saves`, strength-split shots/goals against. `starter` present in 2010 too |
| Play-by-play | **VERIFIED.** `plays[]` with `typeDescKey` (shot-on-goal, missed-shot, blocked-shot, goal, penalty, faceoff, hit, …), `periodDescriptor`, `timeInPeriod`, `situationCode` (4-digit string; on 1551 = 5v5 with both goalies — exact digit order to be confirmed in Phase 1), `homeTeamDefendingSide`, `details.{xCoord,yCoord,zoneCode,shotType,shootingPlayerId,goalieInNetId,eventOwnerTeamId}`; penalties have `typeCode`, `duration`, `committedByPlayerId`, `drawnByPlayerId`. Top level has `startTimeUTC`, `rosterSpots` |
| Play-by-play history | **2010-11: coordinates present** (67/67 shots had x/y, shot type, goalie). **2008-09: no coordinates** (0/54) and only summary events. → xG usable from **2010-11** on. Coverage by season will be measured during ingestion |
| Shift charts (`stats/rest/en/shiftcharts`) | **VERIFIED** for 2023 and 2010 |
| Stats REST game-level (`team/summary`, `goalie/summary` with `isGame=true`) | **VERIFIED.** One row per team-game / goalie-game, including `gamesStarted`, `timeOnIce`, `homeRoad`. Good for cross-checking parsed boxscores |
| Standings by date | **VERIFIED** (200) |
| EDGE history | **VERIFIED: starts 2021-22.** 2020-21 returns 404. `seasonsWithEdgeStats` lists 6 seasons (2021-22 → 2026-27) |
| EDGE granularity | **VERIFIED: season aggregates only.** `team-detail` returns season totals/ranks (shot speed, bursts, max speed, distance, zone-time %, shots by location). Passing a date in place of a season → 404; guessed `/game-log` path → 404. The only per-game data: `skatingDistanceLast10` (team and skater) and `savePctgLast10` (goalie) — the **last 10 games of the queried season**, so historically it only covers each season's final 10 games |
| Partner odds (`/partner-game/US/now`) | **VERIFIED, current only.** `MONEY_LINE_2_WAY` (American), 3-way, puck line, total, plus `bettingPartner`, `lastUpdatedUTC`. No history. Partner/licensing terms unknown → don't rely on it beyond optional personal forward snapshots |
| MoneyPuck | Page text: *"free to use for non-commercial purposes and by journalists for ad-hoc use. Please clearly credit MoneyPuck.com … Non-approved scraping of the [site is not allowed]"*. Shot files (2007→present, 124 attributes, xG scores, blocked shots excluded) are hosted on `peter-tanner.com`, which is **not** on the allowlist yet |

Conclusions that change the plan:
- In-season EDGE features cannot be built leakage-free from history. The only
  options are prior-season EDGE aggregates (usable for 2022-23 onward) or daily
  forward snapshots starting now.
- `starter` is a post-game fact. Using it as a feature is the oracle (leaky) model.
- Baseline data (schedule, results, PBP with coordinates, shifts, goalie
  starts) is sufficient from 2010-11 onward, about 16 regular seasons.

## 0. Blocker: no network access to NHL hosts

The cloud environment's network policy returned HTTP 403 (proxy policy denial) for
every data host tried: `api-web.nhle.com`, `api.nhle.com`, `www.nhl.com`,
`statsapi.web.nhl.com`, `moneypuck.com`, `www.hockey-reference.com`.
Only package indexes (PyPI) and GitHub are reachable.

Consequence: **no endpoint, field name, or history depth below has been confirmed
from this environment.** Everything comes from community documentation
(primarily https://github.com/Zmalski/NHL-API-Reference — the NHL publishes no
official spec) plus third-party write-ups. Each claim is tagged:

- `[DOC]` documented by a community reference, not tested
- `[3P]` third-party claim (blog/scraper), weaker
- `[MEM]` from prior knowledge, weakest — must be verified

To unblock: add `api-web.nhle.com` and `api.nhle.com` (optionally `moneypuck.com`)
to the environment's allowed domains. The first ingestion step will be a
verification script that fetches one sample of each endpoint and writes the
observed schema to `docs/schemas/`, replacing the tags above with `[VERIFIED]`.

## 1. NHL EDGE (puck & player tracking)

### What is exposed `[DOC]`
All under `https://api-web.nhle.com/v1/edge/...`. Every documented endpoint is
parameterized by `{season}/{game-type}` or `now`:

| Group | Examples | Granularity |
|---|---|---|
| Team | `team-detail/{team}/{season}/{gt}`, `team-comparison`, `team-skating-distance-detail`, `team-skating-speed-detail`, `team-zone-time-details`, `team-shot-speed-detail`, `team-shot-location-detail` | season aggregate; distance detail also has "last 10 games" |
| Skater | `skater-detail/{player}/{season}/{gt}`, `skater-skating-speed-detail`, `skater-shot-speed-detail`, `skater-zone-time`, `skater-shot-location-detail` | season aggregate; top-10 individual bursts/shots |
| Goalie | `goalie-detail`, `goalie-5v5-detail`, `goalie-save-percentage-detail`, `goalie-shot-location-detail` | season aggregate + "last 10 games" |
| Leaderboards | `*-top-10/...`, `*-landing` | season |

- No documented endpoint takes a `game-id` or an as-of date.
- `[3P]` A Puck Over The Glass analysis reports that skating **distance** is the
  only metric shown game-by-game on the EDGE site; speed, bursts and shot speed
  are season aggregates.
- `[3P]` NHL.com states EDGE covers every player and club **since 2021-22**
  (regular season and playoffs).

### Implication for modeling (important)
A season-aggregate endpoint queried today returns **end-of-season** values. Using
it as a feature for a game in, say, November of that season would be
leakage. There is no documented way to ask "what was this value as of date D".
So, unless verification finds a game-level or dated endpoint, honest
EDGE features can only come from:

1. **Prior-season EDGE aggregates** (known before the season starts). Legitimate,
   but a weak, slow-moving signal. History: 2021-22 → present, so prior-season
   features are usable for games from 2022-23 onward (~4 seasons, ~5,200 games).
2. **Game-level skating distance**, if it really exists per game (verify).
3. **Forward collection**: snapshot the `now` endpoints daily from today onward,
   giving true as-of values. The 2026-27 season has just started, so this yields
   one season by next spring — too small to evaluate alone, but it's the only
   leakage-free path for in-season EDGE.
4. Differencing consecutive "last 10 games" snapshots — also needs forward collection.

Experiment 2 (EDGE incremental value) is therefore the most constrained of the three
and is likely to be underpowered. I'd recommend running it on (1) now and starting (3)
as a background collection job.

## 2. Standard public NHL endpoints

| Need | Endpoint | Notes |
|---|---|---|
| Schedule | `api-web.nhle.com/v1/club-schedule-season/{team}/{season}`, `/v1/schedule/{date}` `[DOC]` | Game IDs are `SSSSTTNNNN` (season start year, type 02=regular/03=playoff, number) `[MEM]` |
| Results / boxscore | `/v1/gamecenter/{id}/boxscore`, `/landing` `[DOC]` | Expect per-player and per-goalie lines; a goalie `starter` flag is `[MEM]`, verify |
| Play-by-play | `/v1/gamecenter/{id}/play-by-play` `[DOC]` | Expected: event type, period/time, `situationCode`, `details.xCoord/yCoord`, `shotType`, shooter and goalie IDs `[MEM]`. Coverage since 2010-11 per a third-party scraper `[3P]` |
| Shifts | `api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={id}` `[DOC]` | Lets us confirm which goalie was on ice, TOI |
| Game-level team/goalie stats | `api.nhle.com/stats/rest/en/{team,goalie}/summary?isGame=true&cayenneExp=...` `[MEM]` | Useful cross-check for boxscore parsing |
| Standings | `/v1/standings/{date}` `[DOC]` | Dated, so as-of-safe |
| Odds | `/v1/partner-game/{country}/now` `[DOC]` | **Current only**, no history; could be snapshotted forward |

**Sufficiency without EDGE:** yes, if play-by-play coordinates hold up. Shot
location + type + strength state + rebound/rush context is enough for a
standard expected-goals model, and from that Corsi/Fenwick/xG share, goalie
GSAx, special-teams rates, and rest/travel. This is what most public NHL models
are built on. EDGE is an add-on, not a requirement.

### Expected goals source
- **Recommended: build our own xG** from play-by-play, trained strictly
  time-forward (season S's xG model fit only on seasons < S), so xG itself
  cannot leak. Full lineage control.
- **Cross-check: MoneyPuck** shot and team-game data (`[MEM]`: free for
  non-commercial use with attribution, shot data back to 2007; I couldn't open
  their page from here to confirm the license). Caveat: their xG model is fit on
  data including later seasons, so its xG values carry mild look-ahead.
  Fine for validating our xG, not ideal as a feature.

### Goalie starters (largest leakage risk)
- The NHL API tells us who **actually** started (after the fact). It does not
  record when the starter was confirmed. I know of no free, legitimate
  historical source of pre-game confirmed starters with timestamps (sites like
  Daily Faceoff publish them live, but scraping their archives raises ToS issues).
- Proposed handling, reporting both:
  - **Model P (deployable):** a "projected starter" sub-model using only pre-game
    info (rest days, back-to-back, recent workload, season start share, starter
    vs. backup history). Goalie features become an expectation over likely
    starters. This is the honest number.
  - **Model O (oracle, flagged as leaky):** uses the actual starter. Upper bound
    on what confirmed-starter info is worth; real-world value depends on
    getting confirmation before the price moves (the market reacts too).
- The gap between P and O measures how much the starting-goalie announcement is
  worth.

### Injuries / lineups
No historical as-of injury source in the NHL API. Roster endpoints are current
or per-season, not per-date. **Skip and document as a limitation.** A partial proxy:
games missed by top-TOI players derived from prior boxscores (known before the game).

### Terms of use / rate limits
- The NHL API is undocumented and unofficial; NHL.com's terms restrict content to
  personal, non-commercial use. No published rate limit. Plan: ≤1 request/second,
  descriptive User-Agent, exponential backoff on 429/5xx, and a write-once raw
  cache (`data/raw/<source>/<endpoint>/<key>.json.gz` plus a fetch manifest with
  URL, timestamp, HTTP status, sha256). Nothing is ever fetched twice.
- Volume estimate: ~1,312 regular-season games × 3 calls (PBP, boxscore, shifts)
  ≈ 4,000 requests/season → ~1.1 h/season at 1 req/s. 2010-11 → 2025-26 is
  ≈ 60k requests ≈ 17 h, resumable.

### Season irregularities to handle explicitly
2012-13 lockout (48 games); 2019-20 halted in March; 2020-21 56-game
divisional season, mostly without fans (home-ice advantage distorted — flag
or exclude); Atlanta → Winnipeg (2011); Vegas expansion (2017-18); Seattle
(2021-22); Arizona → Utah (2024-25). Teams will be keyed by franchise ID with a
season-specific abbreviation map. Default: regular season only.

## 3a. Free odds sources: terms checked (2026-10-18)

| Source | Coverage (verified) | Terms (verified) | Usable? |
|---|---|---|---|
| SportsbookReviewsOnline archive | NHL 2007-08 → 2022-23, opening/closing moneylines; "will not be updated" | robots.txt allows the archive, but /terms/ says: *"You may not use or reproduce any content or materials on our website without our express written consent."* | **Not without written consent** |
| Kaggle `michaelmallari/sportsbook-odds-on-nhl-games` | 2021-22 and 2022-23 only (2 CSVs, ~69 KB each) | Labeled MIT, but no stated source; appears to re-host SBR data. An uploader's license can't grant rights they don't hold | **Doubtful provenance**; not relied on |
| Princeton DSS Historical Sports Odds Database | 2008–2023 per catalog | Page is behind a bot check ("Verify You Are Human"), which we don't circumvent; access likely limited to Princeton affiliates | Manual inquiry only |
| NHL `partner-game` endpoint | Current games only | NHL's own public API; same personal, non-commercial basis as the rest of the NHL data | Free path, forward collection only |

Conclusion: there is no free historical closing-line source with clean terms. The odds loader
stays source-agnostic, so a file the user is entitled to use (e.g. after SBR grants
consent) can be dropped in later.

## 3. Historical odds — candidate sources

| Source | Coverage | Fields | Access / licensing concerns |
|---|---|---|---|
| Princeton DSS "Historical Sports Odds Database" (dss.princeton.edu, resource 6741) | NHL 2008–2023 `[3P]` | Open & closing moneyline, totals | Appears to mirror the old SportsbookReviewsOnline archive. Access may need a Princeton login; terms unverified. Book is unclear (likely a single book or consensus); no timestamps |
| The Odds API (the-odds-api.com) historical | Featured markets from mid-2020 `[3P]` | Timestamped snapshots per bookmaker | Paid plan; API access permitted by their terms. Best for a timestamp-correct close and CLV |
| Kaggle NHL odds datasets | Varies | Varies | Check each dataset's license and provenance (many re-host scraped data) |
| NHL `partner-game` endpoint | Current only | Partner-book odds | Forward snapshots only |
| Commercial (FantasyData, SportsDataIO, OddsPapi, etc.) | Varies | Varies | Paid; read the terms |

Recommendation: The Odds API historical (2020-21 onward) for timestamped
open/close and CLV, optionally plus the Princeton/SBR archive for longer
closing-line history if its terms allow your use. I will not scrape
sportsbooks or odds sites.

Loader schema (pluggable, CSV/parquet), one row per (game, book, snapshot):

| column | type | notes |
|---|---|---|
| `game_date` | date | local date of game |
| `home_team`, `away_team` | str | mapped to internal franchise codes via an alias table |
| `home_ml`, `away_ml` | int | American odds |
| `snapshot_ts` | timestamp (UTC) | when the price was observed; nullable for sources without it |
| `book` | str | `consensus` allowed |
| `line_type` | enum `open` / `close` / `snapshot` | |
| `source` | str | provenance |

Validation on load: both sides present, implied overround in a sane range
(e.g. 0–10%), unmatched games reported rather than dropped silently.
