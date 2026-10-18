"""Build per-season processed tables from the raw cache, with integrity checks.

    python -m nhlmodel.ingest.process [--season 20232024]

Writes data/processed/<table>/<season>.parquet for tables
events, skater_games, goalie_games, shifts, and a per-season quality report
(data/processed/quality/<season>.parquet) listing, for every game, which raw
documents were present and whether play-by-play goals match the final score.
A season is processed only when all of its raw documents are downloaded,
unless --allow-partial is given.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import pandas as pd

from ..config import load_config, repo_path
from .parse import parse_boxscore, parse_pbp, parse_shifts

RAW = {"pbp": "nhl_web/pbp", "boxscore": "nhl_web/boxscore", "shifts": "nhl_stats/shifts"}


def _load(raw_dir: Path, kind: str, gid: int):
    p = raw_dir / RAW[kind] / str(gid // 1000000) / f"{gid}.json.gz"
    if p.exists():
        return json.loads(gzip.decompress(p.read_bytes()))
    if p.with_name(f"{gid}.404").exists():
        return "404"
    return None


def process_season(raw_dir: Path, out_dir: Path, games: pd.DataFrame, allow_partial: bool = False) -> pd.DataFrame:
    season = int(games["season"].iloc[0])
    events, skaters, goalies, shifts, quality = [], [], [], [], []
    for g in games.itertuples():
        docs = {k: _load(raw_dir, k, g.game_id) for k in RAW}
        q = {"game_id": g.game_id, **{f"has_{k}": isinstance(v, dict) for k, v in docs.items()}}
        q["missing"] = ",".join(k for k, v in docs.items() if v is None)
        if isinstance(docs["pbp"], dict):
            ev = parse_pbp(docs["pbp"])
            events.extend(ev)
            # Shootout "goals" don't count toward the score; the shootout winner gets +1.
            hg = sum(1 for e in ev if e["type"] == "goal" and e["period_type"] != "SO" and e["is_home_event"])
            ag = sum(1 for e in ev if e["type"] == "goal" and e["period_type"] != "SO" and e["is_home_event"] is False)
            so = g.decided_in == "SO"
            q["pbp_goals_match"] = (hg + (so and g.home_win == 1), ag + (so and g.home_win == 0)) == (
                g.home_score, g.away_score)
            q["n_shots_xy"] = sum(1 for e in ev if e["type"] in ("shot-on-goal", "missed-shot", "goal") and e["x"] is not None)
        if isinstance(docs["boxscore"], dict):
            s, gl = parse_boxscore(docs["boxscore"])
            skaters.extend(s)
            goalies.extend(gl)
            q["n_starters"] = sum(1 for r in gl if r["starter"])
        if isinstance(docs["shifts"], dict):
            sh = parse_shifts(docs["shifts"])
            shifts.extend(sh)
            q["n_shifts"] = len(sh)
        quality.append(q)

    qdf = pd.DataFrame(quality)
    if (qdf["missing"] != "").any() and not allow_partial:
        n = int((qdf["missing"] != "").sum())
        raise RuntimeError(f"{season}: {n} games have raw documents not yet downloaded")
    for name, rows in [("events", events), ("skater_games", skaters), ("goalie_games", goalies),
                       ("shifts", shifts), ("quality", quality)]:
        d = out_dir / name
        d.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).convert_dtypes().to_parquet(d / f"{season}.parquet", index=False)
    return qdf


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/data.yaml")
    ap.add_argument("--season", type=int)
    ap.add_argument("--allow-partial", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    raw_dir, out_dir = repo_path(cfg["raw_dir"]), repo_path(cfg["processed_dir"])
    games = pd.read_parquet(out_dir / "games.parquet")
    seasons = [args.season] if args.season else sorted(games["season"].unique())
    for s in seasons:
        q = process_season(raw_dir, out_dir, games[games["season"] == s], args.allow_partial)
        print(
            f"{s}: games={len(q)} pbp={q.has_pbp.mean():.3f} box={q.has_boxscore.mean():.3f} "
            f"shifts={q.has_shifts.mean():.3f} goals_match={q.get('pbp_goals_match', pd.Series(dtype=bool)).mean():.3f} "
            f"two_starters={(q.get('n_starters', pd.Series(dtype=float)) == 2).mean():.3f}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
