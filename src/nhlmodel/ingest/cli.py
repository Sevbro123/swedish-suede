"""Ingestion entry points.

    python -m nhlmodel.ingest.cli schedule            # build data/processed/games.parquet
    python -m nhlmodel.ingest.cli goalies                         # one request per season
    python -m nhlmodel.ingest.cli games --what pbp     [--season 20232024] [--limit N]
    python -m nhlmodel.ingest.cli games --what shifts  (run alongside: different host)

    python -m nhlmodel.ingest.cli update [--days 2] [--lineup-hours 2]   # current season, run daily

Per-game downloads go newest season first. Boxscores are optional (--what boxscore):
goalie starts come from the bulk goalie endpoint and skater TOI from shift charts.

All fetches go through the write-once raw cache, so every command is resumable
and re-running it costs no network calls for data already downloaded.
"""
from __future__ import annotations

import argparse
import sys
import time

import pandas as pd

from ..config import load_config, repo_path
from . import nhl
from .http import CachedClient, NotFound
from .schedule import finalize, season_games

FETCHERS = {"pbp": nhl.play_by_play, "boxscore": nhl.boxscore, "shifts": nhl.shift_chart}
CACHE_PREFIX = {"pbp": "nhl_web/pbp", "boxscore": "nhl_web/boxscore", "shifts": "nhl_stats/shifts"}


def _seasons(cfg) -> list[int]:
    first, last = cfg["seasons"]["first"] // 10000, cfg["seasons"]["last"] // 10000
    return [y * 10000 + y + 1 for y in range(first, last + 1)]


def cmd_schedule(cfg, client: CachedClient) -> None:
    frames = []
    for s in _seasons(cfg):
        raw = season_games(client, s, cfg["seasons"]["game_types"])
        df = finalize(raw)
        exp = raw.attrs.get("expected_regular_season_games")
        print(f"{s}: scheduled={len(raw)} completed={len(df)} expected_total={exp} network_calls={client.network_calls}", flush=True)
        frames.append(df)
    games = pd.concat(frames, ignore_index=True)
    out = repo_path(cfg["processed_dir"]) / "games.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    games.to_parquet(out, index=False)
    print(f"wrote {out} ({len(games)} games)")


def cmd_games(cfg, client: CachedClient, what: list[str], season: int | None, limit: int | None = None) -> None:
    games = pd.read_parquet(repo_path(cfg["processed_dir"]) / "games.parquet")
    if season:
        games = games[games["season"] == season]
    ids = games.sort_values("start_time_utc", ascending=False)["game_id"].tolist()[:limit]
    todo = [(w, g) for g in ids for w in what if not client.is_cached(f"{CACHE_PREFIX[w]}/{g // 1000000}/{g}")]
    print(f"{len(ids)} games x {what}: {len(todo)} fetches needed")
    t0, missing = time.time(), 0
    for i, (w, g) in enumerate(todo, 1):
        try:
            FETCHERS[w](client, g)
        except NotFound:
            missing += 1
        if i % 200 == 0 or i == len(todo):
            rate = i / max(time.time() - t0, 1e-9)
            print(f"  {i}/{len(todo)}  404s={missing}  {rate:.2f} req/s  eta={(len(todo) - i) / rate / 3600:.1f}h", flush=True)


def cmd_goalies(cfg, client: CachedClient) -> None:
    for s in _seasons(cfg):
        for gt in cfg["seasons"]["game_types"]:
            rows = nhl.goalie_games(client, s, gt)
            print(f"{s}: {len(rows)} goalie-games, {len({r['gameId'] for r in rows})} games", flush=True)


def cmd_update(cfg, client: CachedClient, days: float, lineup_hours: float, now: pd.Timestamp | None = None) -> None:
    """Bring the current season up to date and list the next games.

    - schedule: fetched as a dated snapshot every run (it changes daily)
    - per-game play-by-play and shifts: permanent once a game has been final for ``final_settle_hours``
      (NHL stat corrections land within a day); a dated snapshot before that
    - goalie table: dated snapshot
    - confirmed lineups: play-by-play rosterSpots of games starting within ``lineup_hours``, kept once
      both teams list a full lineup
    Writes games.parquet (past seasons unchanged + current-season completed games), upcoming.parquet
    and lineups_confirmed.parquet, then processes the season. Rebuild xG / features / predictions after.
    """
    from .parse import parse_roster
    from .process import process_season, summarize
    from .schedule import upcoming

    season, u = cfg["seasons"]["current"], cfg["update"]
    now = now or pd.Timestamp.now(tz="UTC")
    snap = now.strftime("%Y%m%dT%H%M%SZ")
    proc = repo_path(cfg["processed_dir"])

    raw = season_games(client, season, cfg["seasons"]["game_types"], snapshot=snap,
                       through=(now + pd.Timedelta(days=days + 7)).date())
    done, up = finalize(raw), upcoming(raw, now, days)
    games = pd.read_parquet(proc / "games.parquet")
    games = pd.concat([games[games["season"] != season], done], ignore_index=True)
    games.to_parquet(proc / "games.parquet", index=False)
    up.to_parquet(proc / "upcoming.parquet", index=False)
    print(f"{season}: {len(done)} completed, {len(up)} upcoming within {days} days")

    settled = now - pd.Timedelta(hours=u["final_settle_hours"] + u["game_length_hours"])
    n_perm = n_snap = 0
    for g in done.sort_values("start_time_utc").itertuples():
        perm = g.start_time_utc <= settled
        for w in ("pbp", "shifts"):
            key = f"{CACHE_PREFIX[w]}/{g.game_id // 1000000}/{g.game_id}"
            if client.is_cached(key):
                continue
            n_perm, n_snap = n_perm + perm, n_snap + (not perm)
            try:
                if perm and w == "pbp":
                    FETCHERS[w](client, g.game_id)
                    continue
                doc = FETCHERS[w](client, g.game_id, snap)
                # an empty shift chart means "not posted yet" (NHL gaps, sometimes filled later): keep it
                # as a snapshot only, so the next update asks again instead of freezing the gap
                if perm and doc.get("total"):
                    FETCHERS[w](client, g.game_id)
            except NotFound:
                pass
    nhl.goalie_games(client, season, 2, snapshot=snap)
    print(f"fetched {n_perm} settled and {n_snap} recent (or not yet posted) per-game documents")

    soon = up[up["start_time_utc"] <= now + pd.Timedelta(hours=lineup_hours)]
    path = proc / "lineups_confirmed.parquet"
    lineups = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    for g in soon.itertuples():
        roster = pd.DataFrame(parse_roster(nhl.play_by_play(client, g.game_id, snapshot=snap)))
        n = roster.groupby("team_id").size() if len(roster) else pd.Series(dtype=int)
        # rosterSpots first lists each team's full roster (22-23 players, scratches included) about 80 min
        # before puck drop, then trims to the 20 who dress shortly before it: only the trimmed list counts
        ok = len(n) == 2 and n.between(u["min_lineup_players"], u["max_lineup_players"]).all()
        print(f"  lineup {g.away_abbrev}@{g.home_abbrev}: {'confirmed' if ok else 'not posted yet'}")
        if ok:
            keep = lineups[lineups["game_id"] != g.game_id] if len(lineups) else lineups
            lineups = pd.concat([keep, roster.assign(fetched_at=now)], ignore_index=True)
    if len(lineups):
        lineups.to_parquet(path, index=False)

    q = process_season(repo_path(cfg["raw_dir"]), proc, games[games["season"] == season], allow_partial=True)
    print(summarize(season, q))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/data.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("schedule")
    sub.add_parser("goalies")
    g = sub.add_parser("games")
    g.add_argument("--what", nargs="+", choices=sorted(FETCHERS), default=["pbp", "shifts"])
    g.add_argument("--season", type=int)
    g.add_argument("--limit", type=int, help="only the first N games (smoke test)")
    up = sub.add_parser("update")
    up.add_argument("--days", type=float, default=2, help="list games starting within this many days")
    up.add_argument("--lineup-hours", type=float, default=2, help="look for posted lineups this close to puck drop")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    client = CachedClient.from_config(cfg, repo_path(cfg["raw_dir"]))
    if args.cmd == "schedule":
        cmd_schedule(cfg, client)
    elif args.cmd == "goalies":
        cmd_goalies(cfg, client)
    elif args.cmd == "update":
        cmd_update(cfg, client, args.days, args.lineup_hours)
    else:
        cmd_games(cfg, client, args.what, args.season, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
