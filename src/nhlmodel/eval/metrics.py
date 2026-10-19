"""Probabilistic metrics for P(home win). Accuracy is reported but never used to select models."""
from __future__ import annotations

import numpy as np

EPS = 1e-15


def log_loss_per_game(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    y = np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def brier_per_game(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    return (np.asarray(p, float) - np.asarray(y, float)) ** 2


def accuracy_per_game(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    return ((np.asarray(p) >= 0.5) == (np.asarray(y) == 1)).astype(float)


def calibration_bins(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    """Equal-count bins: mean predicted vs observed rate, with counts (for curves and ECE)."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    order = np.argsort(p, kind="stable")
    out = []
    for idx in np.array_split(order, bins):
        if len(idx):
            out.append({"n": int(len(idx)), "p_mean": float(p[idx].mean()), "y_rate": float(y[idx].mean())})
    return out


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    b = calibration_bins(y, p, bins)
    n = sum(x["n"] for x in b)
    return float(sum(x["n"] * abs(x["y_rate"] - x["p_mean"]) for x in b) / n)


def summary(y: np.ndarray, p: np.ndarray) -> dict:
    return {
        "n": int(len(y)),
        "log_loss": float(log_loss_per_game(y, p).mean()),
        "brier": float(brier_per_game(y, p).mean()),
        "ece": ece(y, p),
        "accuracy": float(accuracy_per_game(y, p).mean()),
    }
