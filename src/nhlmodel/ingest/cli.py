"""Ingestion entry points.

    python -m nhlmodel.ingest.cli schedule            # build data/processed/games.parquet
    python -m nhlmodel.ingest.cli games --what pbp boxscore shifts [--season 20232024] [--limit N]

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
    ids = games["game_id"].tolist()[:limit]
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/data.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("schedule")
    g = sub.add_parser("games")
    g.add_argument("--what", nargs="+", choices=sorted(FETCHERS), default=sorted(FETCHERS))
    g.add_argument("--season", type=int)
    g.add_argument("--limit", type=int, help="only the first N games (smoke test)")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    client = CachedClient.from_config(cfg, repo_path(cfg["raw_dir"]))
    if args.cmd == "schedule":
        cmd_schedule(cfg, client)
    else:
        cmd_games(cfg, client, args.what, args.season, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
