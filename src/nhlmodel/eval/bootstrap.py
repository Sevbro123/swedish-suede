"""Block bootstrap over game days.

All games on one date are resampled together: same-day games share league conditions (and,
for a bettor, the same slate), so treating them as independent would understate uncertainty.
"""
from __future__ import annotations

import numpy as np


def _day_index(days: np.ndarray) -> tuple[np.ndarray, list[np.ndarray]]:
    uniq, inv = np.unique(days, return_inverse=True)
    groups = [np.flatnonzero(inv == k) for k in range(len(uniq))]
    return uniq, groups


def day_block_ci(values: np.ndarray, days: np.ndarray, n_boot: int = 2000, seed: int = 0, alpha: float = 0.05):
    """Mean of per-game ``values`` with a percentile CI from resampling game days."""
    values = np.asarray(values, float)
    _, groups = _day_index(np.asarray(days))
    sums = np.array([values[g].sum() for g in groups])
    counts = np.array([len(g) for g in groups])
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(groups), size=(n_boot, len(groups)))
    boot = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    lo, hi = np.quantile(boot, [alpha / 2, 1 - alpha / 2])
    return float(values.mean()), float(lo), float(hi)


def paired_diff_ci(a: np.ndarray, b: np.ndarray, days: np.ndarray, **kw):
    """Mean of (a - b) per game (e.g. log loss of model A minus model B) with a day-block CI.

    Negative means A is better for a loss. Same resamples for both models, so the CI is on the
    difference itself, which is much tighter than comparing two separate intervals.
    """
    return day_block_ci(np.asarray(a, float) - np.asarray(b, float), days, **kw)
