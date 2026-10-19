import numpy as np
import pandas as pd
import pytest

from nhlmodel.models import families
from nhlmodel.models.families import CALIBRATORS, full_design, full_feature_names, make_family


def frame(n=3000, seed=0):
    rng = np.random.default_rng(seed)
    t = pd.date_range("2015-10-01", periods=n, freq="6h", tz="UTC")
    skill = rng.normal(0, 1, n)
    return pd.DataFrame({
        "start_time_utc": t, "neutral_site": False,
        "home_games_played_season": rng.integers(0, 82, n), "away_games_played_season": rng.integers(0, 82, n),
        "home_xg_share": 0.5 + 0.05 * skill, "away_xg_share": 0.5 - 0.05 * skill,
        "home_leaky_actual_goalie_gsax": rng.normal(size=n), "away_leaky_actual_goalie_gsax": rng.normal(size=n),
        "home_team_id": 1, "away_team_id": 2,
        "home_win": (rng.uniform(size=n) < 1 / (1 + np.exp(-(0.2 + 0.8 * skill)))).astype(int),
    })


def test_full_features_exclude_leaky_and_ids():
    assert full_feature_names(frame()) == ["games_played_season", "xg_share"]  # leaky + id columns dropped
    assert list(full_design(frame()).columns) == ["d_games_played_season", "d_xg_share", "neutral_site",
                                                  "home_games_played_season", "away_games_played_season"]


@pytest.mark.parametrize("calib", ["none", "platt", "isotonic"])
@pytest.mark.parametrize("kind", ["logreg", "rf", "lgbm"])
def test_every_family_fits_and_returns_probabilities(kind, calib):
    f = frame()
    tr, te = f.iloc[:2500], f.iloc[2500:]
    params = {"n_estimators": 50} if kind in ("rf", "lgbm") else {}
    p = make_family({"type": kind, "params": params, "calibration": calib, "calib_games": 500})(tr, te)
    assert p.shape == (500,) and np.all((p > 0) & (p < 1))


def test_calibration_set_is_the_most_recent_games_and_unseen_by_base(monkeypatch):
    f = frame()
    seen = {}
    real = families._base_model

    class Spy:
        def __init__(self, m): self.m = m
        def fit(self, X, y):
            seen["fit_rows"] = X.index.copy(); self.m.fit(X, y); return self
        def predict_proba(self, X): return self.m.predict_proba(X)

    monkeypatch.setattr(families, "_base_model", lambda cfg: Spy(real(cfg)))
    tr, te = f.iloc[:2500], f.iloc[2500:]
    make_family({"type": "logreg", "calibration": "platt", "calib_games": 400})(tr, te)
    assert set(seen["fit_rows"]) == set(tr.index[:2100])  # the last 400 games are held out for calibration


def test_platt_recovers_a_monotone_rescaling():
    rng = np.random.default_rng(1)
    p = rng.uniform(0.3, 0.7, 20000)
    y = (rng.uniform(size=p.size) < np.clip(0.5 + 1.5 * (p - 0.5), 0, 1)).astype(int)
    q = CALIBRATORS["platt"]().fit(p, y).predict(p)
    assert np.corrcoef(q, p)[0, 1] > 0.99 and q.std() > p.std()  # stretched out, order kept


def test_calibration_set_is_capped_for_short_histories(monkeypatch):
    f = frame(n=1500)
    seen = {}
    real = families._base_model

    class Spy:
        def __init__(self, m): self.m = m
        def fit(self, X, y): seen["n"] = len(X); self.m.fit(X, y); return self
        def predict_proba(self, X): return self.m.predict_proba(X)

    monkeypatch.setattr(families, "_base_model", lambda cfg: Spy(real(cfg)))
    make_family({"type": "logreg", "calibration": "platt", "calib_games": 1500})(f.iloc[:1230], f.iloc[1230:])
    assert seen["n"] == 1230 - int(0.2 * 1230)  # 20% held out, not all 1,500


def test_calibration_split_never_splits_simultaneous_games():
    f = frame(n=2000)
    f["start_time_utc"] = f["start_time_utc"].dt.floor("1D")  # four games per start time
    p = make_family({"type": "logreg", "calibration": "platt", "calib_games": 301})(f.iloc[:1600], f.iloc[1600:])
    assert p.shape == (400,)
