"""Pluggable historical odds loader.

Any odds source is first converted (by a source-specific adapter, outside this
module) into CSV or parquet with this schema, one row per (game, book, snapshot):

    column        type                         notes
    game_date     date (YYYY-MM-DD)            local date of the game
    home_team     str                          team abbreviation or name as the source writes it
    away_team     str
    home_ml       int                          American odds
    away_ml       int                          American odds
    snapshot_ts   UTC timestamp, nullable      when the price was observed (null if source lacks it)
    book          str                          "consensus" allowed
    line_type     "open" | "close" | "snapshot"
    source        str                          provenance, e.g. "sbr_archive"

``load_odds`` validates rows; ``match_to_games`` joins them to the games table on
(local game date, home team id, away team id) and reports anything unmatched.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .vig import overround

REQUIRED = ["game_date", "home_team", "away_team", "home_ml", "away_ml", "snapshot_ts", "book", "line_type", "source"]
LINE_TYPES = {"open", "close", "snapshot"}
OVERROUND_RANGE = (0.0, 0.10)


class OddsValidationError(ValueError):
    pass


def load_odds(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    df = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
    return validate_odds(df)


def validate_odds(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise OddsValidationError(f"missing columns: {missing}")
    df = df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date
    df["snapshot_ts"] = pd.to_datetime(df["snapshot_ts"], utc=True)
    bad_type = ~df["line_type"].isin(LINE_TYPES)
    if bad_type.any():
        raise OddsValidationError(f"invalid line_type values: {sorted(df.loc[bad_type, 'line_type'].unique())}")
    if df[["home_ml", "away_ml"]].isna().any().any():
        raise OddsValidationError("null moneyline")
    if ((df["home_ml"].abs() < 100) | (df["away_ml"].abs() < 100)).any():
        raise OddsValidationError("American odds must satisfy |odds| >= 100")
    df["overround"] = overround(df["home_ml"], df["away_ml"])
    lo, hi = OVERROUND_RANGE
    bad = (df["overround"] < lo) | (df["overround"] > hi)
    if bad.any():
        raise OddsValidationError(f"{int(bad.sum())} rows with overround outside [{lo}, {hi}]")
    return df


def match_to_games(
    odds: pd.DataFrame, games: pd.DataFrame, team_alias: dict[str, int]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach ``game_id``. Returns (matched, unmatched). Never drops rows silently.

    ``games`` needs game_id, local_date, home_team_id, away_team_id.
    ``team_alias`` maps every spelling used by the odds source to an NHL team id.
    """
    o = odds.copy()
    o["home_team_id"] = o["home_team"].map(team_alias)
    o["away_team_id"] = o["away_team"].map(team_alias)
    keys = games[["game_id", "local_date", "home_team_id", "away_team_id"]].rename(columns={"local_date": "game_date"})
    m = o.merge(keys, on=["game_date", "home_team_id", "away_team_id"], how="left")
    return m[m["game_id"].notna()].reset_index(drop=True), m[m["game_id"].isna()].reset_index(drop=True)
