"""Run one experiment config through walk-forward evaluation and log it.

    python -m nhlmodel.eval.run configs/experiments/<name>.yaml --period dev|test

Outputs
    results/experiments.csv                      one appended row per run (the results table)
    results/reports/<id>__<period>.json          overall / by season / excl. 2020-21, calibration bins
    results/predictions/<id>__<period>.parquet   out-of-sample P(home win) per game
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yaml

from ..config import load_config, repo_path
from ..models.baselines import make_model
from .bootstrap import day_block_ci
from .metrics import accuracy_per_game, brier_per_game, calibration_bins, log_loss_per_game, summary
from .walkforward import PERIODS, walk_forward

LOG_FIELDS = ["run_id", "date_run", "git_rev", "config_hash", "experiment", "period", "seasons", "split",
              "model", "hyperparams", "feature_groups", "window", "goalie_variant", "n_games",
              "log_loss", "log_loss_lo", "log_loss_hi", "brier", "brier_lo", "brier_hi", "ece", "accuracy",
              "log_loss_excl_2020_21", "notes"]
NO_FANS = 20202021


def load_frame() -> pd.DataFrame:
    proc = repo_path("data/processed")
    feats = pd.read_parquet(proc / "features.parquet")
    labels = pd.read_parquet(proc / "labels.parquet")[["game_id", "home_win"]]
    games = pd.read_parquet(proc / "games.parquet")[["game_id", "local_date"]]
    f = feats.merge(labels, on="game_id", validate="one_to_one").merge(games, on="game_id", validate="one_to_one")
    f["season"] = f["season"].astype(int)
    f["home_win"] = f["home_win"].astype(int)
    return f.sort_values("start_time_utc").reset_index(drop=True)


def _git_rev() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_path("."), capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def evaluate(cfg: dict, period: str, frame: pd.DataFrame | None = None, n_boot: int = 2000) -> dict:
    frame = load_frame() if frame is None else frame
    seasons = PERIODS[period]
    p = walk_forward(frame, make_model(cfg["model"]), seasons)
    ev = frame.loc[p.index].assign(p=p.values)
    y, pr, days = ev["home_win"].to_numpy(), ev["p"].to_numpy(), ev["local_date"].astype(str).to_numpy()
    ll, lo, hi = day_block_ci(log_loss_per_game(y, pr), days, n_boot=n_boot)
    br, blo, bhi = day_block_ci(brier_per_game(y, pr), days, n_boot=n_boot)
    by_season = {}
    for s, d in ev.groupby("season"):
        m = summary(d["home_win"].to_numpy(), d["p"].to_numpy())
        m["log_loss_ci"] = day_block_ci(log_loss_per_game(d["home_win"], d["p"]), d["local_date"].astype(str), n_boot=n_boot)[1:]
        by_season[int(s)] = m
    excl = ev[ev["season"] != NO_FANS]
    return {
        "predictions": ev[["game_id", "season", "local_date", "home_win", "p"]],
        "overall": {**summary(y, pr), "log_loss_ci": [lo, hi], "brier_ci": [blo, bhi]},
        "excl_2020_21": summary(excl["home_win"].to_numpy(), excl["p"].to_numpy()) if len(excl) else None,
        "by_season": by_season,
        "calibration": calibration_bins(y, pr),
        "ll": (ll, lo, hi), "brier": (br, blo, bhi),
    }


def log_run(cfg: dict, period: str, res: dict) -> str:
    m = cfg["model"]
    run_id = f"{cfg['id']}__{period}"
    blob = yaml.safe_dump(cfg, sort_keys=True)
    hyper = {k: v for k, v in m.items() if k not in ("type", "groups", "window", "goalie_variant")}
    o = res["overall"]
    row = {
        "run_id": run_id, "date_run": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "git_rev": _git_rev(),
        "config_hash": hashlib.sha256(blob.encode()).hexdigest()[:10], "experiment": cfg["id"], "period": period,
        "seasons": f"{PERIODS[period][0]}-{PERIODS[period][-1]}",
        "split": "walk-forward, monthly refit, expanding window from 2011-12",
        "model": m["type"], "hyperparams": json.dumps(hyper, sort_keys=True),
        "feature_groups": "+".join(m.get("groups", [])) or m.get("features", "-"), "window": m.get("window", "-"),
        "goalie_variant": m.get("goalie_variant", "-") if "goalie" in m.get("groups", []) else "-",
        "n_games": o["n"], "log_loss": round(o["log_loss"], 5), "log_loss_lo": round(o["log_loss_ci"][0], 5),
        "log_loss_hi": round(o["log_loss_ci"][1], 5), "brier": round(o["brier"], 5), "brier_lo": round(o["brier_ci"][0], 5),
        "brier_hi": round(o["brier_ci"][1], 5), "ece": round(o["ece"], 5), "accuracy": round(o["accuracy"], 4),
        "log_loss_excl_2020_21": round(res["excl_2020_21"]["log_loss"], 5) if res["excl_2020_21"] else "",
        "notes": cfg.get("notes", ""),
    }
    res_dir = repo_path("results")
    path = res_dir / "experiments.csv"
    new = not path.exists()
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    (res_dir / "reports").mkdir(parents=True, exist_ok=True)
    (res_dir / "predictions").mkdir(parents=True, exist_ok=True)
    report = {k: res[k] for k in ("overall", "excl_2020_21", "by_season", "calibration")}
    report.update({"run_id": run_id, "config": cfg, "git_rev": row["git_rev"], "date_run": row["date_run"]})
    (res_dir / "reports" / f"{run_id}.json").write_text(json.dumps(report, indent=1, default=float))
    res["predictions"].to_parquet(res_dir / "predictions" / f"{run_id}.parquet", index=False)
    return run_id


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--period", choices=sorted(PERIODS), default="dev")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    res = evaluate(cfg, args.period)
    rid = log_run(cfg, args.period, res)
    ll, lo, hi = res["ll"]
    print(f"{rid}: log loss {ll:.5f} [{lo:.5f}, {hi:.5f}]  brier {res['overall']['brier']:.5f}  "
          f"ece {res['overall']['ece']:.4f}  acc {res['overall']['accuracy']:.4f}  n={res['overall']['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
