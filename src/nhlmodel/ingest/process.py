"""Build per-season processed tables from the raw cache, with integrity checks.

    python -m nhlmodel.ingest.process [--season 20232024] [--allow-partial]

Writes data/processed/<table>/<season>.parquet for tables
    events        every play-by-play event
    rosters       players listed per game (with position)
    shifts        on-ice shifts
    skater_toi    time on ice per player-game, summed from shifts
    goalie_games  goalie appearances incl. starter flag (bulk stats endpoint)
    quality       per game: raw coverage, pbp goals vs final score, starter count
A season is written only when all of its per-game raw documents are downloaded,
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
from .parse import parse_goalie_games, parse_pbp, parse_roster, parse_shifts

RAW = {"pbp": "nhl_web/pbp", "shifts": "nhl_stats/shifts"}


def _read(path: Path):
    return json.loads(gzip.decompress(path.read_bytes()))


def _load(raw_dir: Path, kind: str, gid: int):
    p = raw_dir / RAW[kind] / str(gid // 1000000) / f"{gid}.json.gz"
    if p.exists():
        return _read(p)
    if p.with_name(f"{gid}.404").exists():
        return "404"
    return None


def _pbp_goals_match(ev: list[dict], g) -> bool:
    # Shootout "goals" don't count individually; the shootout winner is credited one goal.
    hg = sum(1 for e in ev if e["type"] == "goal" and e["period_type"] != "SO" and e["is_home_event"] is True)
    ag = sum(1 for e in ev if e["type"] == "goal" and e["period_type"] != "SO" and e["is_home_event"] is False)
    if g.decided_in == "SO":
        hg, ag = hg + (g.home_win == 1), ag + (g.home_win == 0)
    return (hg, ag) == (g.home_score, g.away_score)


# Summed on-ice time per team (skaters + goalie), minutes: ~6 x 60 in regulation, a bit more with OT.
# Outside this range the shift chart is treated as unreliable for that game.
TEAM_TOI_RANGE_MIN = (320, 420)


def clean_shifts(rows: list[dict], home_id: int, away_id: int) -> tuple[list[dict], dict]:
    """Drop shifts for teams not in the game and exact duplicate rows (both seen in NHL shift charts),
    then flag the game if either team's summed TOI is still implausible."""
    keep, seen = [], set()
    for r in rows:
        key = (r["player_id"], r["period"], r["start_s"], r["end_s"])
        if r["team_id"] in (home_id, away_id) and key not in seen:
            seen.add(key)
            keep.append(r)
    toi = {home_id: 0, away_id: 0}
    for r in keep:
        toi[r["team_id"]] += r["duration_s"] or 0
    lo, hi = TEAM_TOI_RANGE_MIN
    info = {
        "n_shifts": len(keep),
        "n_shifts_dropped": len(rows) - len(keep),
        "home_toi_min": toi[home_id] / 60,
        "away_toi_min": toi[away_id] / 60,
    }
    info["shifts_ok"] = all(lo <= v / 60 <= hi for v in toi.values())
    return keep, info


def process_season(raw_dir: Path, out_dir: Path, games: pd.DataFrame, allow_partial: bool = False) -> pd.DataFrame:
    season = int(games["season"].iloc[0])
    events, rosters, shifts, quality = [], [], [], []
    for g in games.itertuples():
        docs = {k: _load(raw_dir, k, g.game_id) for k in RAW}
        q = {"game_id": g.game_id, **{f"has_{k}": isinstance(v, dict) for k, v in docs.items()}}
        q["missing"] = ",".join(k for k, v in docs.items() if v is None)
        if isinstance(docs["pbp"], dict):
            ev = parse_pbp(docs["pbp"])
            events.extend(ev)
            rosters.extend(parse_roster(docs["pbp"]))
            q["pbp_goals_match"] = _pbp_goals_match(ev, g)
            q["n_unblocked_with_xy"] = sum(
                1 for e in ev if e["type"] in ("shot-on-goal", "missed-shot", "goal") and e["x"] is not None
            )
        if isinstance(docs["shifts"], dict):
            sh, info = clean_shifts(parse_shifts(docs["shifts"]), g.home_team_id, g.away_team_id)
            shifts.extend(sh)
            q.update(info)
        quality.append(q)

    qdf = pd.DataFrame(quality)
    if (qdf["missing"] != "").any() and not allow_partial:
        n = int((qdf["missing"] != "").sum())
        raise RuntimeError(f"{season}: {n} games have raw documents not yet downloaded")

    goalie_path = raw_dir / "nhl_stats" / "goalie_games" / f"{season}_2.json.gz"
    ids = {r.game_id: (r.home_team_id, r.away_team_id) for r in games.itertuples()}
    goalies = parse_goalie_games(_read(goalie_path)["data"], ids) if goalie_path.exists() else []
    starters = pd.Series([r["game_id"] for r in goalies if r["starter"]]).value_counts()
    qdf["n_starters"] = qdf["game_id"].map(starters).fillna(0).astype(int)

    shifts_df = pd.DataFrame(shifts)
    toi = (
        shifts_df.groupby(["game_id", "team_id", "player_id"], as_index=False)["duration_s"].sum()
        .rename(columns={"duration_s": "toi_s"})
        if len(shifts_df) else pd.DataFrame()
    )
    tables = {"events": pd.DataFrame(events), "rosters": pd.DataFrame(rosters), "shifts": shifts_df,
              "skater_toi": toi, "goalie_games": pd.DataFrame(goalies), "quality": qdf}
    for name, df in tables.items():
        d = out_dir / name
        d.mkdir(parents=True, exist_ok=True)
        df.convert_dtypes().to_parquet(d / f"{season}.parquet", index=False)
    return qdf


def summarize(season: int, q: pd.DataFrame) -> str:
    def rate(col, cond=None):
        if col not in q:
            return float("nan")
        s = q[col] if cond is None else cond(q[col])
        return float(s.mean())

    return (
        f"{season}: games={len(q)} pbp={rate('has_pbp'):.3f} shifts={rate('has_shifts'):.3f} "
        f"goals_match={rate('pbp_goals_match'):.3f} two_starters={rate('n_starters', lambda s: s == 2):.3f} "
        f"shifts_ok={rate('shifts_ok'):.3f} xy_shots/game={q['n_unblocked_with_xy'].mean() if 'n_unblocked_with_xy' in q else float('nan'):.1f}"
    )


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
        print(summarize(s, q), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
