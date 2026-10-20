"""One command for live use: bring the current season up to date, predict, and rebuild the site.

    python -m nhlmodel.live [--days 2] [--lineup-hours 2] [--no-fetch]

Steps: ``cli update`` (schedule, new games, goalie table, posted lineups) -> xG for the current season
-> features -> predictions for each team's next game -> this season's completed games re-predicted the
backtest way (monthly refits, only earlier games) -> predictions log -> site/index.html.

The predictions log (data/processed/predictions_log.csv) keeps the last prediction made before each
game's start, so the site can show the live record. It is also copied to site/ (the GitHub Action
carries it between runs on the ``site`` branch).
"""
from __future__ import annotations

import argparse
import shutil
import sys

import pandas as pd

from .config import load_config, repo_path
from .eval.run import load_frame
from .eval.walkforward import walk_forward
from .models.baselines import make_model

LOG_COLS = ["game_id", "made_at", "p_home", "lineup"]


def prune_snapshots(raw_dir, keep_days: float, now: pd.Timestamp) -> int:
    """Delete snapshot folders older than ``keep_days``: every run re-fetches what it needs from them."""
    snap, n = raw_dir / "snap", 0
    if not snap.exists():
        return 0
    for d in snap.iterdir():
        try:
            t = pd.Timestamp(d.name.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t < now - pd.Timedelta(days=keep_days):
            shutil.rmtree(d)
            n += 1
    return n


def update_log(log: pd.DataFrame, preds: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Upsert this run's predictions (all for games that haven't started) into the log."""
    new = preds.assign(made_at=now.isoformat())[LOG_COLS]
    keep = log[~log["game_id"].isin(set(new["game_id"]))] if len(log) else log
    return pd.concat([keep, new], ignore_index=True).sort_values("game_id").reset_index(drop=True)


def season_so_far(cfg_path: str, season: int) -> pd.DataFrame:
    """This season's completed games, predicted as in the backtests: refit monthly on earlier games only."""
    frame = load_frame()
    if not (frame["season"] == season).any():
        return pd.DataFrame(columns=["game_id", "p"])
    p = walk_forward(frame, make_model(load_config(cfg_path)["model"]), [season])
    return frame.loc[p.index, ["game_id"]].assign(p=p.to_numpy())


def main(argv: list[str] | None = None) -> int:
    from .features import build as fbuild
    from .ingest.cli import cmd_update
    from .ingest.http import CachedClient
    from .predict import PROJECTED, predict_explained
    from .report.build import build as build_site
    from .xg.model import run as run_xg

    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=2)
    ap.add_argument("--lineup-hours", type=float, default=2)
    ap.add_argument("--no-fetch", action="store_true", help="skip the NHL fetch (rebuild from what's on disk)")
    args = ap.parse_args(argv)

    cfg = load_config("configs/data.yaml")
    season, proc, raw = cfg["seasons"]["current"], repo_path(cfg["processed_dir"]), repo_path(cfg["raw_dir"])
    now = pd.Timestamp.now(tz="UTC")
    if not args.no_fetch:
        print(f"pruned {prune_snapshots(raw, 2, now)} old snapshot folders")
        cmd_update(cfg, CachedClient.from_config(cfg, raw), args.days, args.lineup_hours, now)
    run_xg(load_config("configs/xg.yaml"), only=season)
    fbuild.main([])

    feats, labels = pd.read_parquet(proc / "features.parquet"), pd.read_parquet(proc / "labels.parquet")
    up = pd.read_parquet(proc / "upcoming.parquet")
    up = up[up["start_time_utc"] > now]
    lp = proc / "lineups_confirmed.parquet"
    confirmed = set(pd.read_parquet(lp)["game_id"]) if lp.exists() else set()
    preds, terms = predict_explained(feats, labels, up, confirmed)
    preds.assign(made_at=now.isoformat()).to_parquet(proc / "predictions_upcoming.parquet", index=False)
    terms.to_parquet(proc / "explain_upcoming.parquet", index=False)
    print(f"predicted {len(preds)} upcoming games")

    season_so_far(PROJECTED, season).to_parquet(proc / "predictions_season.parquet", index=False)

    log_path = proc / "predictions_log.csv"
    log = pd.read_csv(log_path) if log_path.exists() else pd.DataFrame(columns=LOG_COLS)
    if len(preds):
        log = update_log(log, preds, now)
    log.to_csv(log_path, index=False)

    out = repo_path("site")
    path = build_site(cfg, out)
    shutil.copy(log_path, out / "predictions_log.csv")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
