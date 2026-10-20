"""Assemble the model-ready tables.

    python -m nhlmodel.features.build [--config configs/features/base.yaml]

Writes
    data/processed/features.parquet   one row per game; pre-game information only (no outcome columns)
    data/processed/labels.parquet     game_id, season, home_win, decided_in, plus evaluation flags

Keeping labels in a separate file means the feature table cannot carry the outcome by construction;
models join the two on game_id. Goalie features come in three variants (actual / projected /
expected); see features/goalies.py. The *actual* variant reads each game's post-game starter flag
and is a leaky upper bound, so its columns are prefixed ``leaky_`` to make that impossible to miss.
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from ..config import load_config, repo_path
from .asof import build_features
from .goalies import goalie_features, goalie_games_with_xg
from .players import lineup_features, player_games, player_states
from .team_games import build_team_games

OUTCOME_COLS = {"home_score", "away_score", "home_win", "decided_in", "last_period_type", "game_state"}


def _read_seasons(kind: str, seasons) -> pd.DataFrame:
    proc = repo_path("data/processed")
    paths = [proc / kind / f"{s}.parquet" for s in seasons if (proc / kind / f"{s}.parquet").exists()]
    return pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True) if paths else pd.DataFrame()


def _lineups(games: pd.DataFrame, events: pd.DataFrame, xg: pd.DataFrame, seasons, cfg: dict) -> pd.DataFrame:
    """Player on-ice metrics (seasons with xG and shift charts) -> lineup features per team-game."""
    pgs = []
    for s in seasons:
        sh, xs = _read_seasons("shifts", [s]), xg[xg["game_id"].isin(set(games.loc[games["season"] == s, "game_id"]))]
        if sh.empty or xs.empty:  # burn-in season has no xG
            continue
        q = _read_seasons("quality", [s])
        bad = set(q.loc[~q["shifts_ok"].fillna(False).astype(bool), "game_id"])
        ev = events[events["game_id"].isin(set(sh["game_id"]))]
        pgs.append(player_games(ev, sh, xs, _read_seasons("rosters", [s]), bad))
    states = player_states(pd.concat(pgs, ignore_index=True), games, cfg["players"])
    return lineup_features(_read_seasons("rosters", seasons), games, states, cfg["players"], cfg.get("lineage", {}))


def assemble(cfg: dict, data_cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    games = pd.read_parquet(repo_path(data_cfg["processed_dir"]) / "games.parquet")
    seasons = sorted(games["season"].unique())
    events = _read_seasons("events", seasons)
    xg = _read_seasons("xg", seasons)
    xg = xg if len(xg) else None

    tg = build_team_games(events, games, xg, cfg.get("adjust"))
    feats = build_features(games, tg, cfg)

    gg = goalie_games_with_xg(xg, _read_seasons("goalie_games", seasons), games) if xg is not None else None
    if gg is not None:
        gf = goalie_features(gg, games, cfg["goalies"])
        gf = gf.rename(columns={c: f"leaky_{c}" for c in gf.columns if c.startswith("actual_")})
        gf = gf.drop(columns=["projection_correct"])
        cols = [c for c in gf.columns if c not in ("game_id", "team_id")]
        for side in ("home", "away"):
            side_f = gf.rename(columns={c: f"{side}_{c}" for c in cols})
            feats = feats.merge(side_f, left_on=["game_id", f"{side}_team_id"], right_on=["game_id", "team_id"],
                                how="left").drop(columns=["team_id"])

    if "players" in cfg and xg is not None:
        lf = _lineups(games, events, xg, seasons, cfg)
        cols = [c for c in lf.columns if c not in ("game_id", "team_id")]
        for side in ("home", "away"):
            side_f = lf.rename(columns={c: f"{side}_{c}" for c in cols})
            feats = feats.merge(side_f, left_on=["game_id", f"{side}_team_id"], right_on=["game_id", "team_id"],
                                how="left").drop(columns=["team_id"])

    leak = OUTCOME_COLS & set(feats.columns)
    if leak:
        raise AssertionError(f"outcome columns in feature table: {sorted(leak)}")

    flags = data_cfg.get("flags", {})
    labels = games[["game_id", "season", "home_win", "decided_in", "neutral_site"]].copy()
    labels["flag_no_fans"] = labels["season"].isin(flags.get("no_fans", [])).astype(int)
    labels["flag_shortened"] = labels["season"].isin(flags.get("shortened", [])).astype(int)
    return feats.sort_values("start_time_utc").reset_index(drop=True), labels


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/features/base.yaml")
    ap.add_argument("--data-config", default="configs/data.yaml")
    args = ap.parse_args(argv)
    cfg, data_cfg = load_config(args.config), load_config(args.data_config)
    feats, labels = assemble(cfg, data_cfg)
    out = repo_path(data_cfg["processed_dir"])
    feats.to_parquet(out / "features.parquet", index=False)
    labels.to_parquet(out / "labels.parquet", index=False)
    print(f"features: {feats.shape[0]} games x {feats.shape[1]} columns; labels: {len(labels)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
