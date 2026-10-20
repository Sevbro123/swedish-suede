"""Rolling re-selection check: does re-picking the model each season beat picking it once?

    python -m nhlmodel.eval.rolling [--config configs/experiments/rolling.yaml]

Every candidate in the config is run once, walk-forward, over the development and test seasons
(cached in results/rolling/candidates.parquet). For each test season S, a selection rule picks the
candidate with the lowest log loss on seasons before S (all of them, or the last N); the picked
candidate's predictions for S are used. "fixed" picks once on the development seasons. Picks for S
read only seasons before S, and every candidate's predictions are walk-forward, so nothing from S
or later is used.

Outputs: results/rolling/summary.json and a printed table of picks and paired comparisons.
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import pandas as pd

from ..config import load_config, repo_path
from ..models.baselines import make_model
from .bootstrap import day_block_ci, paired_diff_ci
from .metrics import log_loss_per_game
from .run import load_frame
from .walkforward import PERIODS, walk_forward


def candidate_configs(cfg: dict) -> dict[str, dict]:
    """Candidate name -> model config, one per (family, C)."""
    out = {}
    for fam, spec in cfg["candidates"].items():
        for c in spec["C"]:
            if "groups" in spec:
                m = {"type": "logreg", "C": c, "groups": spec["groups"], "window": "std", "goalie_variant": "expected"}
            else:
                m = {"type": "logreg", "params": {"C": c}, "features": spec["features"], "calibration": "none"}
            out[f"{fam}_C{c}"] = m
    return out


def run_candidates(cfg: dict, frame: pd.DataFrame, seasons: list[int]) -> pd.DataFrame:
    """One row per game: game_id, season, local_date, home_win, then P(home win) per candidate."""
    base = None
    for name, m in candidate_configs(cfg).items():
        p = walk_forward(frame, make_model(m), seasons)
        if base is None:
            base = frame.loc[p.index, ["game_id", "season", "local_date", "home_win"]].copy()
        base[name] = p.to_numpy()
        print(f"  ran {name}", flush=True)
    return base.reset_index(drop=True)


def pick(losses: pd.DataFrame, season: int, window: int | None, eligible: list[int]) -> str:
    """Candidate with the lowest mean log loss on ``eligible`` seasons before ``season`` (last ``window``)."""
    prior = [s for s in eligible if s < season]
    if window:
        prior = prior[-window:]
    if not prior:
        raise ValueError(f"no seasons before {season} to select on")
    return losses[losses["season"].isin(prior)].drop(columns=["season"]).mean().idxmin()


def evaluate(cands: pd.DataFrame, cfg: dict, dev: list[int], test: list[int], n_boot: int = 2000) -> dict:
    names = [c for c in cands.columns if c not in ("game_id", "season", "local_date", "home_win")]
    y = cands["home_win"].to_numpy()
    losses = pd.DataFrame({n: log_loss_per_game(y, cands[n].to_numpy()) for n in names})
    losses["season"] = cands["season"].to_numpy()
    eligible = sorted(set(dev) | set(test))

    rules = {"fixed": {s: pick(losses, dev[-1] + 10001, None, dev) for s in test}}
    for rule, window in cfg["selection_windows"].items():
        rules[rule] = {s: pick(losses, s, window, eligible) for s in test}

    in_test = cands["season"].isin(test).to_numpy()
    days = cands.loc[in_test, "local_date"].astype(str).to_numpy()
    seas = cands.loc[in_test, "season"].to_numpy()
    per_game = {r: np.array([losses.loc[in_test, picks[s]].to_numpy()[i] for i, s in enumerate(seas)])
                for r, picks in rules.items()}
    out = {"n_test_games": int(in_test.sum()), "rules": {}, "paired_vs_fixed": {}, "by_season": {}}
    for r, ll in per_game.items():
        m, lo, hi = day_block_ci(ll, days, n_boot=n_boot)
        out["rules"][r] = {"log_loss": m, "ci": [lo, hi], "picks": {str(s): rules[r][s] for s in test}}
        if r != "fixed":
            d, dlo, dhi = paired_diff_ci(ll, per_game["fixed"], days, n_boot=n_boot)
            out["paired_vs_fixed"][r] = {"diff": d, "ci": [dlo, dhi], "within_noise": bool(dlo <= 0 <= dhi)}
    for s in test:
        k = seas == s
        out["by_season"][str(s)] = {r: float(ll[k].mean()) for r, ll in per_game.items()}
    # context: each candidate held fixed over all test seasons
    out["candidates_test"] = {n: float(losses.loc[in_test, n].mean()) for n in names}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/experiments/rolling.yaml")
    ap.add_argument("--rerun", action="store_true", help="recompute candidate predictions even if cached")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    dev, test = PERIODS["dev"], PERIODS["test"]
    out_dir = repo_path("results/rolling")
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / "candidates.parquet"
    if cache.exists() and not args.rerun:
        cands = pd.read_parquet(cache)
    else:
        cands = run_candidates(cfg, load_frame(), dev + test)
        cands.to_parquet(cache, index=False)
    res = evaluate(cands, cfg, dev, test)
    (out_dir / "summary.json").write_text(json.dumps(res, indent=2))

    print(f"test seasons, n={res['n_test_games']}")
    for r, v in res["rules"].items():
        print(f"  {r:10s} log loss {v['log_loss']:.5f} [{v['ci'][0]:.5f}, {v['ci'][1]:.5f}]")
    for r, v in res["paired_vs_fixed"].items():
        verdict = "within noise" if v["within_noise"] else ("better" if v["ci"][1] < 0 else "worse")
        print(f"  {r} - fixed: {v['diff']:+.5f} [{v['ci'][0]:+.5f}, {v['ci'][1]:+.5f}]  {verdict}")
    print("picks per test season:")
    for s in test:
        print(f"  {s}: " + "  ".join(f"{r}={res['rules'][r]['picks'][str(s)]}" for r in res["rules"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
