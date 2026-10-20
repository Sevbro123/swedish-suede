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


def actual_lineup(frame: pd.DataFrame) -> pd.DataFrame:
    """Lineup columns filled from the actual (``leaky_``) lineup: the posted lineup at puck drop."""
    f = frame.copy()
    for c in [c for c in f.columns if c.startswith(("home_leaky_lineup_", "away_leaky_lineup_"))]:
        f[c.replace("leaky_", "", 1)] = f[c]
    return f


def _inputs(cfg: dict[str, Any], train: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """(train sorted by time, test, feature names), with the actual lineup swapped in if the config asks."""
    if cfg.get("lineup") == "actual":
        train, test = actual_lineup(train), actual_lineup(test)
    feats = cfg.get("features", "full")
    names = full_feature_names(train, adjusted=feats == "full_adjusted", lineup=feats == "full_lineup")
    return train.sort_values("start_time_utc"), test, names


def explain_family(cfg: dict[str, Any]):
    """fit_explain(train, test) -> (p, terms) for an uncalibrated logistic family: the same fit as
    ``make_family``, plus each test game's log-odds split into additive terms.

    The model is standardize -> logistic, so log-odds = intercept + sum_j coef_j * (x_j - mean_j) / scale_j
    = [intercept - sum_j coef_j * mean_j / scale_j] + sum_j (coef_j / scale_j) * x_j. Terms use the second
    form: x_j = 0 means "no home-minus-away difference", so a term is how far that difference moves the
    log-odds away from evenly matched teams. ``terms`` has one row per (test game, term): ``term`` is a
    design column (or "intercept"), ``logit`` its share of the log-odds, and ``home`` / ``away`` the raw
    per-side values behind it.
    """
    if cfg["type"] != "logreg" or cfg.get("calibration", "none") != "none":
        raise ValueError("only an uncalibrated logistic model splits into additive terms")

    def fit_explain(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
        train, test, names = _inputs(cfg, train, test)
        m = _base_model(cfg).fit(full_design(train, names), train["home_win"])
        X = full_design(test, names)
        scaler, lr = m[0], m[-1]
        w = lr.coef_[0] / scaler.scale_
        logit = X * w
        logit["intercept"] = lr.intercept_[0] - float(w @ scaler.mean_)
        home = pd.DataFrame({f"d_{n}": test[f"home_{n}"].astype(float) for n in names}, index=test.index)
        away = pd.DataFrame({f"d_{n}": test[f"away_{n}"].astype(float) for n in names}, index=test.index)
        home["home_games_played_season"] = X["home_games_played_season"]
        away["away_games_played_season"] = X["away_games_played_season"]
        home["neutral_site"] = away["neutral_site"] = X["neutral_site"]
        def long(df: pd.DataFrame, name: str) -> pd.DataFrame:
            df = df.reindex(columns=logit.columns).assign(game_id=test["game_id"].to_numpy())
            return df.melt(id_vars="game_id", var_name="term", value_name=name)

        terms = long(logit, "logit").assign(home=long(home, "home")["home"], away=long(away, "away")["away"])
        return m.predict_proba(X)[:, 1], terms

    return fit_explain


def make_family(cfg: dict[str, Any]):
    """fit_predict(train, test) for walk_forward. ``lineup: actual`` trains and predicts with the actual
    lineup in the lineup columns (an upper bound in backtests; deployable once lineups are posted)."""
    calib = cfg.get("calibration", "none")
    n_cal = cfg.get("calib_games", 1500)

    def fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
        train, test, names = _inputs(cfg, train, test)
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
