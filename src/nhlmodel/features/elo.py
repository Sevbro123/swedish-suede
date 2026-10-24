"""Elo results rating: each franchise's rating from the wins and goal margins of its earlier games.

One pass over the games in start-time order. A game's row holds both teams' ratings *before* it, then the
ratings move by k * ln(|goal margin| + 1) * (result - expected); the expectation gives the home team ``hfa``
Elo points (none at a neutral site). Between seasons a rating keeps ``carry`` of its distance from 1500.
Games not played yet (no score) get the current ratings and move nothing. Overtime and shootout wins count
as wins, as the moneyline settles them. Settings are fixed in advance, not tuned:
configs/features/base.yaml ``elo``.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .asof import franchise_ids


def elo_ratings(games: pd.DataFrame, cfg: dict[str, Any], lineage: dict[int, int]) -> pd.DataFrame:
    """Per (game_id, team_id): ``elo_rating`` before the game (1500 = average)."""
    k, hfa, carry = cfg["k"], cfg["hfa"], cfg["carry"]
    g = games.sort_values("start_time_utc")
    hf = franchise_ids(g["home_team_id"], lineage).to_numpy()
    af = franchise_ids(g["away_team_id"], lineage).to_numpy()
    rating: dict[int, float] = {}
    season_of: dict[int, int] = {}
    pre_h, pre_a = np.empty(len(g)), np.empty(len(g))
    rows = zip(hf, af, g["season"], g["home_score"], g["away_score"], g["neutral_site"])
    for i, (h, a, season, hs, as_, neutral) in enumerate(rows):
        for t in (h, a):
            if t not in rating:
                rating[t], season_of[t] = 1500.0, season
            elif season_of[t] != season:
                rating[t], season_of[t] = 1500 + carry * (rating[t] - 1500), season
        pre_h[i], pre_a[i] = rating[h], rating[a]
        if pd.isna(hs) or pd.isna(as_):
            continue
        expected = 1 / (1 + 10 ** (-(rating[h] - rating[a] + (0 if neutral else hfa)) / 400))
        move = k * np.log(abs(hs - as_) + 1) * ((1.0 if hs > as_ else 0.0) - expected)
        rating[h] += move
        rating[a] -= move
    return pd.concat([
        pd.DataFrame({"game_id": g["game_id"].to_numpy(), "team_id": g["home_team_id"].to_numpy(), "elo_rating": pre_h}),
        pd.DataFrame({"game_id": g["game_id"].to_numpy(), "team_id": g["away_team_id"].to_numpy(), "elo_rating": pre_a}),
    ], ignore_index=True)
