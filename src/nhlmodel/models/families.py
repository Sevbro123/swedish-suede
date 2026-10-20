"""Phase 3 model families on one shared design matrix.

All families see the SAME features (``full_design``) and the same walk-forward splits, so
differences come from the model, not the inputs.

Calibration (optional, any family): inside each refit, the training pool is split by time.
The most recent ``calib_games`` games before the refit cutoff (at most ``calib_max_frac`` = 20% of
the pool, for early refits with little history) form the calibration set; the
base model is fit only on the games before them, and the calibrator (Platt = logistic on the
logit, or isotonic) is fit on the base model's predictions for the calibration set. Test games
are never touched, and the calibration games are never in the base model's training data.
"""
from __future__ import annotations

from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

EXCLUDE_PREFIXES = ("leaky_", "projected_")
# Score/venue-adjusted shot stats (features/adjust.py) were added after Phase 3 was frozen; the
# "full" matrix leaves them out so frozen configs reproduce, and ``features: full_adjusted`` adds them.
ADJUSTED_TAGS = ("_sa_", "_sva_")
# Lineup features (features/players.py), likewise added after Phase 3: ``features: full_lineup``.
LINEUP_TAG = "lineup_"


def full_feature_names(frame: pd.DataFrame, adjusted: bool = False, lineup: bool = False) -> list[str]:
    """Per-side features that have both a home_ and an away_ column and are known pre-game."""
    names = []
    for c in frame.columns:
        if not c.startswith("home_"):
            continue
        base = c[5:]
        if f"away_{base}" not in frame.columns or base == "team_id" or base.endswith("_id"):
            continue
        if base.startswith(EXCLUDE_PREFIXES):
            continue
        if not adjusted and any(t in base for t in ADJUSTED_TAGS):
            continue
        if not lineup and base.startswith(LINEUP_TAG):
            continue
        names.append(base)
    return sorted(names)


def full_design(frame: pd.DataFrame, names: list[str] | None = None) -> pd.DataFrame:
    """Home-minus-away differences for every pre-game feature, plus context columns.

    Missing values become 0 ("no difference") for every family alike, so the inputs are identical.
    """
    names = names or full_feature_names(frame)
    cols = {f"d_{n}": frame[f"home_{n}"].astype(float) - frame[f"away_{n}"].astype(float) for n in names}
    cols["neutral_site"] = frame["neutral_site"].astype(float)
    cols["home_games_played_season"] = frame["home_games_played_season"].astype(float)
    cols["away_games_played_season"] = frame["away_games_played_season"].astype(float)
    return pd.DataFrame(cols, index=frame.index).fillna(0.0)


def _base_model(cfg: dict[str, Any]):
    kind, p = cfg["type"], cfg.get("params", {})
    if kind == "logreg":
        return make_pipeline(StandardScaler(), LogisticRegression(C=p.get("C", 0.01), max_iter=5000))
    if kind == "rf":
        return RandomForestClassifier(
            n_estimators=p.get("n_estimators", 500), max_depth=p.get("max_depth"),
            min_samples_leaf=p.get("min_samples_leaf", 50), max_features=p.get("max_features", "sqrt"),
            n_jobs=p.get("n_jobs", 4), random_state=p.get("seed", 0))
    if kind == "lgbm":
        return lgb.LGBMClassifier(
            n_estimators=p.get("n_estimators", 300), learning_rate=p.get("learning_rate", 0.02),
            num_leaves=p.get("num_leaves", 7), min_child_samples=p.get("min_child_samples", 200),
            subsample=p.get("subsample", 0.8), subsample_freq=1, colsample_bytree=p.get("colsample_bytree", 0.5),
            reg_lambda=p.get("reg_lambda", 5.0), random_state=p.get("seed", 0), deterministic=True,
            force_row_wise=True, n_jobs=p.get("n_jobs", 4), verbose=-1)
    raise ValueError(f"unknown family {kind!r}")


class _Platt:
    def fit(self, p, y):
        z = np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1)).reshape(-1, 1)
        self.m = LogisticRegression(C=1e6, max_iter=1000).fit(z, y)
        return self

    def predict(self, p):
        z = np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1)).reshape(-1, 1)
        return self.m.predict_proba(z)[:, 1]


class _Isotonic:
    def fit(self, p, y):
        self.m = IsotonicRegression(out_of_bounds="clip", y_min=1e-4, y_max=1 - 1e-4).fit(p, y)
        return self

    def predict(self, p):
        return self.m.predict(p)


CALIBRATORS = {"platt": _Platt, "isotonic": _Isotonic}


def make_family(cfg: dict[str, Any]):
    """fit_predict(train, test) for walk_forward."""
    calib = cfg.get("calibration", "none")
    n_cal = cfg.get("calib_games", 1500)

    def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
        feats = cfg.get("features", "full")
        names = full_feature_names(train, adjusted=feats == "full_adjusted", lineup=feats == "full_lineup")
        train = train.sort_values("start_time_utc")
        if calib == "none":
            m = _base_model(cfg).fit(full_design(train, names), train["home_win"])
            return m.predict_proba(full_design(test, names))[:, 1]
        # Early refits have little history (the first dev refit trains on 2011-12 alone), so the
        # calibration set is capped at a fraction of the pool rather than taking all of it.
        k = min(n_cal, int(cfg.get("calib_max_frac", 0.2) * len(train)))
        if len(train) - k < 500:
            raise ValueError(f"only {len(train) - k} games left to fit the base model before calibration")
        # split at a time boundary: games often share a start time, and a row-count split could
        # put simultaneous games on both sides
        t_cut = train["start_time_utc"].iloc[-k]
        fit_part, cal_part = train[train["start_time_utc"] < t_cut], train[train["start_time_utc"] >= t_cut]
        if fit_part["start_time_utc"].max() >= cal_part["start_time_utc"].min():
            raise AssertionError("calibration set must come strictly after the base model's training data")
        m = _base_model(cfg).fit(full_design(fit_part, names), fit_part["home_win"])
        c = CALIBRATORS[calib]().fit(m.predict_proba(full_design(cal_part, names))[:, 1], cal_part["home_win"].to_numpy())
        return c.predict(m.predict_proba(full_design(test, names))[:, 1])

    return fit_predict
