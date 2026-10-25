"""One command for live use: bring the current season up to date, predict, and rebuild the site.

    python -m nhlmodel.live [--days 2] [--lineup-hours 2] [--no-fetch]

Steps: ``cli update`` (schedule, new games, goalie table, posted lineups) -> xG for the current season
-> features -> predictions for each team's next game -> this season's completed games re-predicted the
backtest way (monthly refits, only earlier games) -> predictions log -> paper bets -> site/index.html.

The predictions log (data/processed/predictions_log.csv) keeps the last prediction made before each
game's start, so the site can show the live record. It is also copied to site/ (the GitHub Action
carries it between runs on the ``site`` branch). The odds log (the partner book's moneylines, read each
run) and the paper parlays (paper_parlays.csv) travel the same way; the single paper bets are rebuilt from
the two logs every run (``nhlmodel.paper``).
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


def record_odds(cfg, client, now: pd.Timestamp) -> int:
    """Append the partner book's current moneylines to the odds log. Never fails the run: a missing price
    only means no bet on that game."""
    from .odds.partner import ODDS_COLS, append_log, fetch

    path = repo_path(cfg["processed_dir"]) / "odds_log.csv"
    log = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=ODDS_COLS)
    try:
        new = fetch(client, now)
    except Exception as e:  # noqa: BLE001 - odds are optional
        print(f"odds: partner fetch failed ({e!r}), no prices this run", flush=True)
        return 0
    n = len(log)
    log = append_log(log, new)
    log.to_csv(path, index=False)
    books = ", ".join(sorted(set(new["book"]))) or "no book"
    print(f"odds: {len(new)} games priced ({books}), {len(log) - n} new prices", flush=True)
    return len(new)


def paper_trade(proc, log: pd.DataFrame, now: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rebuild the paper bets from the predictions and odds logs and update the parlays (``nhlmodel.paper``).
    Returns (bets, parlay legs)."""
    from .paper import BET_COLS, LEG_COLS, build_bets, grade_parlays, update_parlays

    lp, op = proc / "paper_parlays.csv", proc / "odds_log.csv"
    legs = pd.read_csv(lp) if lp.exists() else pd.DataFrame(columns=LEG_COLS)
    if not op.exists():
        return pd.DataFrame(columns=BET_COLS), legs
    games = pd.concat([pd.read_parquet(proc / "games.parquet"), pd.read_parquet(proc / "upcoming.parquet")])
    games = games.drop_duplicates("game_id")[["game_id", "start_time_utc", "local_date", "away_abbrev", "home_abbrev", "home_win"]]
    cfg = load_config("configs/paper.yaml")
    bets = build_bets(log, pd.read_csv(op), games, cfg, now, grade_parlays(legs, games, now))
    return bets, update_parlays(legs, bets, cfg, now)


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
        client = CachedClient.from_config(cfg, raw)
        cmd_update(cfg, client, args.days, args.lineup_hours, now)
        record_odds(cfg, client, now)
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
    bets, legs = paper_trade(proc, log, now)
    bets.to_csv(proc / "paper_bets.csv", index=False)
    legs.to_csv(proc / "paper_parlays.csv", index=False)
    print(f"paper trading: {int((bets['side'].fillna('') != '').sum())} bets on {len(bets)} priced games, "
          f"{legs['date'].nunique()} parlays")

    out = repo_path("site")
    path = build_site(cfg, out)
    for name in ("predictions_log.csv", "odds_log.csv", "paper_bets.csv", "paper_parlays.csv"):
        if (proc / name).exists():
            shutil.copy(proc / name, out / name)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
