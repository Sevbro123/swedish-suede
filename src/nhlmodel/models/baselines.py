"""Phase 2 baselines.

A: constant P(home win) = home win rate in the training games (the probabilistic form of
   "always pick the home team").
B: L2-regularised logistic regression on a small set of home-minus-away differences.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

# Feature groups -> per-side column templates ({w} = team-strength window, {g} = goalie variant)
GROUPS = {
    "xg_share": ["{w}_xg_5v5_share", "{w}_xg_share"],
    # 5v5 xG share adjusted for score (sa) or score and venue (sva); see features/adjust.py
    "xg_share_sa": ["{w}_xg_5v5_sa_share", "{w}_xg_share"],
    "xg_share_sva": ["{w}_xg_5v5_sva_share", "{w}_xg_share"],
    "goalie": ["{g}_goalie_gsax100_ewm"],
    # lineup from player on-ice xG (features/players.py): projected (previous game) or leaky actual
    "lineup": ["lineup_on_xg_share", "lineup_rel_xg_share", "lineup_missing_toi_share"],
    "lineup_leaky": ["leaky_lineup_on_xg_share", "leaky_lineup_rel_xg_share", "leaky_lineup_missing_toi_share"],
    "rest": ["rest_days", "back_to_back"],
}
GOALIE_PREFIX = {"expected": "expected", "projected": "projected", "actual": "leaky_actual"}


def design_columns(cfg: dict[str, Any]) -> list[str]:
    w, g = cfg.get("window", "std"), GOALIE_PREFIX[cfg.get("goalie_variant", "expected")]
    return [c.format(w=w, g=g) for grp in cfg["groups"] if grp in GROUPS for c in GROUPS[grp]]


def design_matrix(frame: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Home-minus-away differences, plus a neutral-site indicator if 'home' is a group.

    Missing values (a franchise's first games, burn-in xG) become 0 = "no difference".
    """
    X = pd.DataFrame(index=frame.index)
    for c in design_columns(cfg):
        X[f"d_{c}"] = frame[f"home_{c}"].astype(float) - frame[f"away_{c}"].astype(float)
    if "home" in cfg["groups"]:
        X["neutral_site"] = frame["neutral_site"].astype(float)
    return X.fillna(0.0)


def fit_predict_constant(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    return np.full(len(test), train["home_win"].mean())


def make_logreg(cfg: dict[str, Any]):
    def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
        Xtr, Xte = design_matrix(train, cfg), design_matrix(test, cfg)
        m = make_pipeline(StandardScaler(), LogisticRegression(C=cfg.get("C", 1.0), max_iter=2000))
        m.fit(Xtr, train["home_win"])
        return m.predict_proba(Xte)[:, 1]
    return fit_predict


def make_model(cfg: dict[str, Any]):
    """Baselines (constant / logreg on a named feature set) or a Phase 3 family on the full matrix."""
    kind = cfg["type"]
    if kind == "constant":
        return fit_predict_constant
    if kind == "logreg" and "groups" in cfg:
        return make_logreg(cfg)
    from .families import make_family
    return make_family(cfg)
