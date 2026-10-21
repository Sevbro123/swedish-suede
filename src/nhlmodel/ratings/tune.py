"""Choose the RAPM settings on the development seasons only.

    python -m nhlmodel.ratings.tune [--lams 300 1000] [--halflives 24 none] [--append]

For each ridge penalty ``lam`` and decay half-life, fits the monthly ratings (only up to the end of
the development period, so no test-period rating is ever computed here), adds the projected
lineup's ``rapm_*`` features to the feature table, and runs Baseline B + ``rapm`` through the dev
walk-forward. Writes ``results/rapm_grid.csv``.
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from ..config import load_config, repo_path
from ..eval.run import evaluate, load_frame
from ..eval.walkforward import PERIODS
from ..features.build import _read_seasons, _schedule, lineup_inputs, load_stints
from ..features.players import rapm_lineup_features
from .rapm import fit_monthly, month_of, monthly_equations

LAMS = [300, 1000, 3000]
HALFLIVES = [12, 24, 48, None]
B_RAPM = {"type": "logreg", "C": 0.01, "groups": ["xg_share", "goalie", "rest", "home", "rapm"],
          "window": "std", "goalie_variant": "expected"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lams", type=float, nargs="*", default=LAMS)
    ap.add_argument("--halflives", nargs="*", default=HALFLIVES)
    ap.add_argument("--append", action="store_true", help="add rows to results/rapm_grid.csv")
    args = ap.parse_args(argv)
    halflives = [None if h in (None, "none") else float(h) for h in args.halflives]
    cfg, data_cfg = load_config("configs/features/base.yaml"), load_config("configs/data.yaml")
    done, games = _schedule(repo_path(data_cfg["processed_dir"]))
    last_dev = max(PERIODS["dev"])
    dev_games = games[games["season"] <= last_dev]
    seasons = sorted(dev_games["season"].unique())
    events, xg = _read_seasons("events", seasons), _read_seasons("xg", seasons)
    sides, members = lineup_inputs(dev_games, events, xg, seasons, cfg)
    del events
    player_index, eqs = monthly_equations(load_stints(seasons), dev_games)
    cutoffs = sorted(month_of(dev_games["start_time_utc"]).unique())

    frame = load_frame()
    frame = frame[frame["season"] <= last_dev].drop(columns=[c for c in frame.columns if "rapm_" in c])
    rows = []
    for hl in halflives:
        for lam in args.lams:
            ratings = fit_monthly(player_index, eqs, cutoffs, lam, hl)
            rf = rapm_lineup_features(sides, members, ratings)
            f = frame
            for side in ("home", "away"):
                cols = {c: f"{side}_{c}" for c in rf.columns if c not in ("game_id", "team_id")}
                f = f.merge(rf.rename(columns=cols), left_on=["game_id", f"{side}_team_id"],
                            right_on=["game_id", "team_id"], how="left").drop(columns=["team_id"])
            f = f.sort_values("start_time_utc").reset_index(drop=True)
            res = evaluate({"model": B_RAPM}, "dev", f, n_boot=200)
            rows.append({"lam": int(lam), "halflife_months": int(hl) if hl is not None else "none",
                         "dev_log_loss": round(res["ll"][0], 6), "n_games": len(res["predictions"])})
            print(rows[-1], flush=True)
    out = repo_path("results/rapm_grid.csv")
    new = pd.DataFrame(rows)
    if args.append and out.exists():
        new = pd.concat([pd.read_csv(out), new], ignore_index=True)
    new.to_csv(out, index=False)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
