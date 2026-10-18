"""Moneyline conversion and vig removal.

American odds: -150 means stake 150 to win 100; +130 means stake 100 to win 130.
Implied probability (with vig) = 1 / decimal odds. The two sides' implied
probabilities sum to 1 + overround.

Vig-removal methods:
- ``multiplicative`` (proportional normalization): p_i / sum(p). Standard default.
- ``power``: find k with sum(p_i ** k) = 1. Shifts more of the margin onto the
  longshot (favourite-longshot bias); a common alternative.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import brentq


def american_to_decimal(ml):
    ml = np.asarray(ml, dtype=float)
    if np.any(np.abs(ml) < 100):
        raise ValueError("American odds must satisfy |odds| >= 100")
    return np.where(ml > 0, 1 + ml / 100.0, 1 + 100.0 / np.abs(ml))


def american_to_implied(ml):
    return 1.0 / american_to_decimal(ml)


def overround(home_ml, away_ml):
    """Sum of implied probabilities minus 1 (e.g. 0.045 = 4.5% margin)."""
    return american_to_implied(home_ml) + american_to_implied(away_ml) - 1.0


def _power_one(ph: float, pa: float) -> float:
    if abs(ph + pa - 1.0) < 1e-12:
        return ph
    k = brentq(lambda k: ph**k + pa**k - 1.0, 1e-6, 50.0)
    return ph**k


def devig(home_ml, away_ml, method: str = "multiplicative"):
    """Return the vig-free home-win probability."""
    ph, pa = american_to_implied(home_ml), american_to_implied(away_ml)
    if method == "multiplicative":
        return ph / (ph + pa)
    if method == "power":
        out = np.vectorize(_power_one, otypes=[float])(ph, pa)
        return out if out.ndim else float(out)
    raise ValueError(f"unknown devig method {method!r}")


def profit_per_unit(ml, won):
    """Net profit of a 1-unit stake at American odds ``ml``: (decimal - 1) if won, else -1."""
    dec = american_to_decimal(ml)
    return np.where(np.asarray(won, dtype=bool), dec - 1.0, -1.0)
