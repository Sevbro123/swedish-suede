import numpy as np
import pandas as pd
import pytest

from nhlmodel.eval.bootstrap import day_block_ci, paired_diff_ci
from nhlmodel.eval.metrics import brier_per_game, calibration_bins, ece, log_loss_per_game, summary
from nhlmodel.eval.walkforward import PERIODS, TRAIN_START, walk_forward
from nhlmodel.models.baselines import design_matrix, fit_predict_constant


def test_log_loss_and_brier_known_values():
    assert log_loss_per_game([1], [0.5])[0] == pytest.approx(np.log(2))
    assert log_loss_per_game([0], [0.25])[0] == pytest.approx(-np.log(0.75))
    assert brier_per_game([1, 0], [0.8, 0.3]).tolist() == pytest.approx([0.04, 0.09])
    assert np.isfinite(log_loss_per_game([1], [0.0])[0])  # clipped, not inf


def test_ece_and_bins():
    rng = np.random.default_rng(1)
    p = rng.uniform(0.3, 0.7, 100_000)
    y = (rng.uniform(size=p.size) < p).astype(int)
    assert ece(y, p) < 0.01
    assert ece(y, np.clip(p + 0.1, 0, 1)) > 0.08
    assert sum(b["n"] for b in calibration_bins(y, p)) == len(p)


def test_summary_fields():
    s = summary(np.array([1, 0, 1]), np.array([0.6, 0.4, 0.7]))
    assert s["accuracy"] == 1.0 and s["n"] == 3


def test_day_block_ci_contains_mean_and_identical_models_differ_by_zero():
    rng = np.random.default_rng(2)
    v = rng.normal(0.68, 0.1, 5000)
    days = np.repeat(np.arange(500), 10)
    m, lo, hi = day_block_ci(v, days, n_boot=500)
    assert lo < m < hi
    d, dlo, dhi = paired_diff_ci(v, v, days, n_boot=200)
    assert d == dlo == dhi == 0.0


def test_day_blocks_widen_ci_when_games_on_a_day_are_correlated():
    rng = np.random.default_rng(3)
    days = np.repeat(np.arange(300), 10)
    day_effect = np.repeat(rng.normal(0, 1, 300), 10)
    v = day_effect + rng.normal(0, 0.2, days.size)
    _, lo_b, hi_b = day_block_ci(v, days, n_boot=500)
    _, lo_i, hi_i = day_block_ci(v, np.arange(days.size), n_boot=500)
    assert (hi_b - lo_b) > 2 * (hi_i - lo_i)


def _frame():
    rows = []
    for s in [20112012] + PERIODS["dev"][:2]:
        y = s // 10000
        for d in pd.date_range(f"{y}-10-05", f"{y + 1}-04-10", freq="3D", tz="UTC"):
            rows.append({"game_id": len(rows), "season": s, "start_time_utc": d + pd.Timedelta(hours=23), "home_win": len(rows) % 2})
    return pd.DataFrame(rows)


def test_walk_forward_never_trains_on_the_present_or_future():
    f = _frame()
    seen = []

    def spy(train, test):
        assert train["start_time_utc"].max() < test["start_time_utc"].min()
        assert (train["season"] >= TRAIN_START).all()
        seen.append(len(test))
        return np.full(len(test), 0.5)

    p = walk_forward(f, spy, PERIODS["dev"][:2])
    assert len(p) == (f["season"].isin(PERIODS["dev"][:2])).sum() == sum(seen)
    assert len(seen) >= 12  # monthly refits


def test_constant_baseline_uses_training_rate_only():
    train = pd.DataFrame({"home_win": [1, 1, 0, 1]})
    assert fit_predict_constant(train, pd.DataFrame(index=range(3))).tolist() == [0.75] * 3


def test_design_matrix_differences_and_missing():
    f = pd.DataFrame({"home_std_xg_5v5_share": [0.55, np.nan], "away_std_xg_5v5_share": [0.50, 0.5],
                      "home_std_xg_share": [0.5, 0.5], "away_std_xg_share": [0.5, 0.5],
                      "neutral_site": [False, True]})
    X = design_matrix(f, {"groups": ["xg_share", "home"], "window": "std"})
    assert X["d_std_xg_5v5_share"].tolist() == pytest.approx([0.05, 0.0])
    assert X["neutral_site"].tolist() == [0.0, 1.0]
