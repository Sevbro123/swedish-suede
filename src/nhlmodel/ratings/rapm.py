"""Regularized adjusted plus-minus (RAPM) on 5v5 xG, refit at every month boundary.

Each stint (``ratings/stints.py``) gives two rows, one per attacking team. The target is the
attacking team's xG per 60 minutes, weighted by stint minutes. Columns:

- intercept, attacking team at home, attacking team trailing, attacking team leading (unpenalized)
- one offense coefficient per attacking skater and one defense coefficient per defending skater

so each player gets ``off`` (xG/60 their team creates above average while they're on) and ``def``
(xG/60 their team allows *below* average: the fitted coefficient with its sign flipped, so higher
is better for both). Teammates and opponents are adjusted for because they are in the same rows.

Ridge penalty ``lam`` (in minutes of 5v5 play) pulls every player toward 0 = league average.
Players with little ice time stay close to it. Older data is down-weighted with a half-life in
calendar months (``halflife_months``, None = no decay), which carries ratings across seasons
without letting old seasons count fully. (The spec's alternative, a prior from the previous fit,
counts each stint again at every refit; decaying the normal equations does the same job with one
setting.)

As-of rule (the walk-forward rule): ratings for any game in calendar month M (UTC) are fit only on
stints from games that started before the first day of M.

Implementation: the normal equations X'WX and X'Wy are additive over stints, so they are summed
per month once; each refit decays and adds them, then solves one sparse system by conjugate gradient.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.sparse.linalg import cg, spsolve

from .stints import AWAY, HOME

N_COV = 4  # intercept, home, trailing, leading
COV_LAM = 1e-6


def month_of(ts: pd.Series) -> pd.Series:
    return ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.to_period("M")


def _rows(idx_att: np.ndarray, idx_def: np.ndarray, home: bool, lead: np.ndarray, n_players: int) -> sp.csr_matrix:
    n = len(lead)
    cols = [np.zeros(n, int)]
    if home:
        cols.append(np.ones(n, int))
    rows = [np.arange(n)] * len(cols)
    trail, ahead = lead < 0, lead > 0
    r = np.arange(n)
    rows += [r[trail], r[ahead]]
    cols += [np.full(trail.sum(), 2), np.full(ahead.sum(), 3)]
    rows += [np.repeat(r, 5), np.repeat(r, 5)]
    cols += [N_COV + idx_att.ravel(), N_COV + n_players + idx_def.ravel()]
    rr, cc = np.concatenate(rows), np.concatenate(cols)
    return sp.csr_matrix((np.ones(len(rr)), (rr, cc)), shape=(n, N_COV + 2 * n_players))


def normal_equations(stints: pd.DataFrame, player_index: pd.Index) -> tuple[sp.csr_matrix, np.ndarray]:
    """X'WX and X'Wy for these stints (W = stint minutes, y = xG per 60, so Wy = 60 * xG)."""
    P = len(player_index)
    h = player_index.get_indexer(stints[HOME].to_numpy().ravel()).reshape(-1, 5)
    a = player_index.get_indexer(stints[AWAY].to_numpy().ravel()).reshape(-1, 5)
    lead = stints["home_lead"].to_numpy()
    w = stints["dur_s"].to_numpy(float) / 60
    A, b = None, None
    for X, wy in ((_rows(h, a, True, lead, P), 60 * stints["xg_home"].to_numpy(float)),
                  (_rows(a, h, False, -lead, P), 60 * stints["xg_away"].to_numpy(float))):
        XtW = X.T.multiply(w).tocsr()
        A = XtW @ X if A is None else A + XtW @ X
        b = X.T @ wy if b is None else b + X.T @ wy
    return A.tocsr(), b


def monthly_equations(stints: pd.DataFrame, games: pd.DataFrame) -> tuple[pd.Index, dict]:
    """Player index and {month: (X'WX, X'Wy)} summed over the stints of games that started in that month."""
    ids = np.unique(stints[HOME + AWAY].to_numpy().ravel())
    player_index = pd.Index(ids)
    month = month_of(games.set_index("game_id")["start_time_utc"])
    m = stints["game_id"].map(month)
    if m.isna().any():
        raise ValueError("stints for games missing from the games table")
    return player_index, {k: normal_equations(s, player_index) for k, s in stints.groupby(m, sort=True)}


def fit_monthly(player_index: pd.Index, eqs: dict, cutoffs: list, lam: float,
                halflife_months: float | None) -> pd.DataFrame:
    """Ratings as of the first day of each month in ``cutoffs`` (pandas Periods, ascending).

    Returns month, player_id, off, def, toi_min (decayed 5v5 minutes the fit saw)."""
    P = len(player_index)
    K = N_COV + 2 * P
    decay = 1.0 if halflife_months is None else 0.5 ** (1 / halflife_months)
    pen = sp.diags(np.r_[np.full(N_COV, COV_LAM), np.full(2 * P, lam)])
    months = sorted(eqs)
    A, b, beta = sp.csr_matrix((K, K)), np.zeros(K), np.zeros(K)
    out = []
    cur = months[0] if months else None
    for c in sorted(cutoffs):
        while cur is not None and cur < c:  # add every month that ended before cutoff c
            A, b = A * decay, b * decay
            if cur in eqs:
                A, b = A + eqs[cur][0], b + eqs[cur][1]
            cur = cur + 1
        if A.nnz == 0:
            continue
        # conjugate gradient, warm-started from the previous month's fit (a direct sparse solve gives
        # the same ratings to ~1e-9 but takes ~2 s per refit)
        M = (A + pen).tocsr()
        beta, info = cg(M, b, x0=beta, rtol=1e-12, atol=0.0, maxiter=20000, M=sp.diags(1 / M.diagonal()))
        if info != 0:
            beta = spsolve(M.tocsc(), b)
        toi = A.diagonal()[N_COV:N_COV + P]
        seen = toi > 0
        out.append(pd.DataFrame({"month": c, "player_id": player_index[seen], "off": beta[N_COV:N_COV + P][seen],
                                 "def": -beta[N_COV + P:][seen], "toi_min": toi[seen]}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["month", "player_id", "off", "def", "toi_min"])


def player_ratings(stints: pd.DataFrame, games: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Ratings for every month in which a game in ``games`` starts (as of that month's first day)."""
    player_index, eqs = monthly_equations(stints, games)
    cutoffs = sorted(month_of(games["start_time_utc"]).unique())
    return fit_monthly(player_index, eqs, cutoffs, cfg["lam"], cfg.get("halflife_months"))
