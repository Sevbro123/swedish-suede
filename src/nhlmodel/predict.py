"""Predict upcoming games (after ``python -m nhlmodel.ingest.cli update`` and a feature rebuild).

    python -m nhlmodel.predict

Trains on every completed game and predicts each team's next game from data/processed/upcoming.parquet.
Two models, both frozen configs:
- projected lineup (previous game's skaters): ``lu_logreg_full_C0.001``
- confirmed lineup, once both teams have posted one (``cli update`` near puck drop):
  ``lu_logreg_full_actual_C0.001``, trained with actual lineups in the lineup columns
A game is predicted only when it is each team's next game, so no unplayed game sits in its history.

Writes data/processed/predictions_upcoming.parquet (and explain_upcoming.parquet: each prediction split into
per-input terms, for the site's game cards) and prints the table. Analysis only, not betting advice.
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from .config import load_config, repo_path
from .models.families import explain_family

PROJECTED = "configs/experiments/lineup/lu_logreg_full_C0.001.yaml"
CONFIRMED = "configs/experiments/lineup/lu_logreg_full_actual_C0.001.yaml"


def next_games(up: pd.DataFrame) -> pd.DataFrame:
    """Upcoming games that are both teams' next game."""
    up = up.sort_values("start_time_utc")
    seen, keep = set(), []
    for g in up.itertuples():
        if g.home_team_id not in seen and g.away_team_id not in seen:
            keep.append(g.game_id)
        seen |= {g.home_team_id, g.away_team_id}
    return up[up["game_id"].isin(keep)]


def predict_explained(features: pd.DataFrame, labels: pd.DataFrame, up: pd.DataFrame,
                      confirmed_ids: set[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(predictions, terms): ``terms`` splits each prediction's log-odds into one row per model input
    (``models.families.explain_family``), from the same fit that made the prediction."""
    train = features.merge(labels[["game_id", "home_win"]], on="game_id", validate="one_to_one")
    train = train.sort_values("start_time_utc").reset_index(drop=True)
    games = next_games(up)
    test = features[features["game_id"].isin(set(games["game_id"]))].reset_index(drop=True)
    if test.empty:
        return pd.DataFrame(), pd.DataFrame()
    out = test[["game_id", "start_time_utc"]].copy()
    out["p_home"], terms = explain_family(load_config(PROJECTED)["model"])(train, test)
    out["lineup"] = "projected"
    conf = test["game_id"].isin(confirmed_ids).to_numpy()
    if conf.any():
        fit = explain_family(load_config(CONFIRMED)["model"])  # applies actual_lineup itself
        out.loc[conf, "p_home"], conf_terms = fit(train, test[conf])
        out.loc[conf, "lineup"] = "confirmed"
        terms = pd.concat([terms[~terms["game_id"].isin(set(conf_terms["game_id"]))], conf_terms], ignore_index=True)
    meta = up[["game_id", "local_date", "away_abbrev", "home_abbrev"]]
    preds = out.merge(meta, on="game_id")[["game_id", "local_date", "start_time_utc", "away_abbrev", "home_abbrev",
                                           "p_home", "lineup"]].sort_values("start_time_utc")
    return preds, terms


def predict(features: pd.DataFrame, labels: pd.DataFrame, up: pd.DataFrame, confirmed_ids: set[int]) -> pd.DataFrame:
    return predict_explained(features, labels, up, confirmed_ids)[0]


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser().parse_args(argv)
    proc = repo_path("data/processed")
    features, labels = pd.read_parquet(proc / "features.parquet"), pd.read_parquet(proc / "labels.parquet")
    up = pd.read_parquet(proc / "upcoming.parquet")
    up = up[up["start_time_utc"] > pd.Timestamp.now(tz="UTC")]
    lp = proc / "lineups_confirmed.parquet"
    confirmed = set(pd.read_parquet(lp)["game_id"]) if lp.exists() else set()
    res, terms = predict_explained(features, labels, up, confirmed)
    res.to_parquet(proc / "predictions_upcoming.parquet", index=False)
    terms.to_parquet(proc / "explain_upcoming.parquet", index=False)
    print(f"trained on {len(labels)} completed games; {len(res)} upcoming games (each team's next game)")
    for r in res.itertuples():
        print(f"  {r.local_date}  {r.away_abbrev:>3} @ {r.home_abbrev:<3}  home {100 * r.p_home:5.1f}%  "
              f"away {100 * (1 - r.p_home):5.1f}%  lineup: {r.lineup}")
    print("analysis only, not betting advice")
    return 0


if __name__ == "__main__":
    sys.exit(main())
