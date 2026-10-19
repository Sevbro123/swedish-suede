"""Walk-forward, expanding-window evaluation (see docs/eval_protocol.md).

For every month of every evaluated season, the model is refit on all games that started before
the first day of that month, then predicts that month's games.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

PERIODS = {
    "dev": [20122013, 20132014, 20142015, 20152016, 20162017, 20172018],
    "test": [20182019, 20192020, 20202021, 20212022, 20222023, 20232024, 20242025, 20252026],
}
TRAIN_START = 20112012  # 2010-11 is feature burn-in (no xG) and never used


def month_blocks(frame: pd.DataFrame, seasons: list[int]):
    """Yield (refit_cutoff, test_index) for each calendar month of each evaluated season."""
    month = frame["start_time_utc"].dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("M")  # UTC months
    for s in seasons:
        in_s = frame["season"] == s
        for m in sorted(month[in_s].unique()):
            yield pd.Timestamp(m.start_time, tz="UTC"), frame.index[in_s & (month == m)]


def walk_forward(frame: pd.DataFrame, fit_predict: Callable[[pd.DataFrame, pd.DataFrame], np.ndarray],
                 seasons: list[int]) -> pd.Series:
    """Out-of-sample P(home win) for every game in ``seasons``.

    ``frame`` has one row per game with features, ``home_win``, ``season`` and ``start_time_utc``.
    ``fit_predict(train, test)`` must fit on ``train`` only and return probabilities for ``test``.
    """
    pred = pd.Series(np.nan, index=frame.index)
    pool = frame[frame["season"] >= TRAIN_START]
    for cutoff, idx in month_blocks(frame, seasons):
        train = pool[pool["start_time_utc"] < cutoff]
        test = frame.loc[idx]
        if (test["start_time_utc"] < cutoff).any() or (train["start_time_utc"] >= cutoff).any():
            raise AssertionError("walk-forward split violated")
        pred.loc[idx] = fit_predict(train, test)
    return pred.loc[frame["season"].isin(seasons)]
