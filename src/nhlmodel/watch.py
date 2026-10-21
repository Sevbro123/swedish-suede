"""Stay up through the game window and rerun the live pipeline as soon as a lineup posts.

    python -m nhlmodel.watch [--hours 5.5] [--horizon 4] [--window 25] [--publish scripts/publish_site.sh]

Runs ``nhlmodel.live`` once, then watches the games starting within ``--window`` minutes: it polls their
play-by-play rosterSpots every minute and, when a team's dressed lineup appears, reruns the pipeline (and the
publish command) right away. It stops after ``--hours`` or once no game starts within ``--horizon`` hours.

Why a watcher and not fixed run times (seen live on 2026-10-20): dressed lineups land in rosterSpots only
5-15 minutes before puck drop, sometimes after it, and GitHub starts scheduled runs late or not at all (the
14:15 UTC run started at 18:27; two of the five evening runs never ran). A run 25-55 minutes before puck drop
can't see the lineup, and a run needed at a given minute may never come.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

import pandas as pd

from .config import load_config, repo_path


def plan(up: pd.DataFrame, now: pd.Timestamp, horizon_h: float, window_min: float) -> tuple[list[int], pd.Timestamp | None]:
    """Games to poll now (not started, starting within ``window_min``) and when to look again.

    The wake-up time is ``None`` when no game starts within ``horizon_h``: nothing left to watch.
    """
    t = up.loc[up["start_time_utc"] > now, ["game_id", "start_time_utc"]]
    if t.empty or t["start_time_utc"].min() > now + pd.Timedelta(hours=horizon_h):
        return [], None
    poll = t.loc[t["start_time_utc"] <= now + pd.Timedelta(minutes=window_min), "game_id"].tolist()
    if poll:
        return poll, now + pd.Timedelta(minutes=1)
    # sleep until the next game enters the window, waking at least every 10 min
    nxt = t["start_time_utc"].min() - pd.Timedelta(minutes=window_min)
    return [], min(nxt, now + pd.Timedelta(minutes=10))


def run_pipeline(publish: str | None) -> None:
    from .live import main as live

    live([])
    if publish:
        subprocess.run([publish], check=True)


def main(argv: list[str] | None = None) -> int:
    from .ingest.cli import lineup_status
    from .ingest.http import CachedClient

    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=5.5, help="stop after this long")
    ap.add_argument("--horizon", type=float, default=4, help="stop once no game starts within this many hours")
    ap.add_argument("--window", type=float, default=25, help="poll lineups of games starting within this many minutes")
    ap.add_argument("--publish", help="command to run after each pipeline run (e.g. scripts/publish_site.sh)")
    args = ap.parse_args(argv)

    cfg = load_config("configs/data.yaml")
    proc = repo_path(cfg["processed_dir"])
    client = CachedClient.from_config(cfg, repo_path(cfg["raw_dir"]))
    deadline = pd.Timestamp.now(tz="UTC") + pd.Timedelta(hours=args.hours)

    run_pipeline(args.publish)
    posted: set[int] = set()   # lineups already used by a pipeline run
    while (now := pd.Timestamp.now(tz="UTC")) < deadline:
        up = pd.read_parquet(proc / "upcoming.parquet")
        poll, wake = plan(up, now, args.horizon, args.window)
        if wake is None:
            print(f"{now:%H:%M}Z: no game starts within {args.horizon} h, done", flush=True)
            break
        if poll:
            snap = now.strftime("%Y%m%dT%H%M%SZ")
            games = up[up["game_id"].isin(poll) & ~up["game_id"].isin(posted)]
            new = {g.game_id for g in games.itertuples() if lineup_status(cfg, client, g, snap)[0]}
            if new:
                print(f"{now:%H:%M}Z: {len(new)} new lineup(s) posted, rerunning", flush=True)
                run_pipeline(args.publish)
                posted |= new
                continue
        time.sleep(max((min(wake, deadline) - pd.Timestamp.now(tz="UTC")).total_seconds(), 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
