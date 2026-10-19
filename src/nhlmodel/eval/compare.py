"""Paired comparison of two runs on the same games.

    python -m nhlmodel.eval.compare <run_id_a> <run_id_b>

Reports the mean per-game difference (A minus B) in log loss and Brier with a day-block bootstrap
CI. Negative = A better. "within noise" when the 95% interval includes 0.
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from ..config import repo_path
from .bootstrap import paired_diff_ci
from .metrics import brier_per_game, log_loss_per_game


def compare(run_a: str, run_b: str, n_boot: int = 2000) -> dict:
    d = repo_path("results/predictions")
    a, b = pd.read_parquet(d / f"{run_a}.parquet"), pd.read_parquet(d / f"{run_b}.parquet")
    m = a.merge(b[["game_id", "p"]], on="game_id", suffixes=("_a", "_b"), validate="one_to_one")
    if len(m) != len(a) or len(m) != len(b):
        raise ValueError("runs cover different games; compare runs on the same period")
    y, days = m["home_win"].to_numpy(), m["local_date"].astype(str).to_numpy()
    out = {"n": len(m)}
    for name, f in (("log_loss", log_loss_per_game), ("brier", brier_per_game)):
        diff, lo, hi = paired_diff_ci(f(y, m["p_a"]), f(y, m["p_b"]), days, n_boot=n_boot)
        verdict = "within noise" if lo <= 0 <= hi else (f"{run_a} better" if hi < 0 else f"{run_b} better")
        out[name] = {"diff": diff, "lo": lo, "hi": hi, "verdict": verdict}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_a")
    ap.add_argument("run_b")
    a = ap.parse_args(argv)
    r = compare(a.run_a, a.run_b)
    for k in ("log_loss", "brier"):
        x = r[k]
        print(f"{a.run_a} - {a.run_b}  {k}: {x['diff']:+.5f} [{x['lo']:+.5f}, {x['hi']:+.5f}]  {x['verdict']}  (n={r['n']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
