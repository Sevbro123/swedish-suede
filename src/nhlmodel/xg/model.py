"""Expected-goals model on unblocked shot attempts, trained strictly time-forward.

    python -m nhlmodel.xg.model [--config configs/xg.yaml]

For each season S, the model is fit only on seasons < S and then scores S's shots, so a shot's
xG never depends on its own season or later. The first season in the data has no xG (burn-in).

Shots: goals, shots on goal and missed shots; shootouts and penalty shots excluded. Blocked shots
are excluded because their recorded location is the block, not the shot.

Attack direction: from ``homeTeamDefendingSide`` (home defends left -> home attacks +x; verified on
2023-24) when present; otherwise the majority sign of x over that team's offensive-zone shots in the
same game and period (agrees with the field on 99.98% of 2023-24 shots; needed for older seasons).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

from ..config import load_config, repo_path

UNBLOCKED = ["goal", "shot-on-goal", "missed-shot"]
ATTEMPTS = UNBLOCKED + ["blocked-shot"]
SHOT_TYPES = ["wrist", "snap", "slap", "backhand", "tip-in", "deflected", "wrap-around", "bat", "between-legs",
              "cradle", "poke"]
PREV_TYPES = ["faceoff", "shot-on-goal", "missed-shot", "blocked-shot", "goal", "hit", "giveaway", "takeaway",
              "stoppage", "penalty"]
NET_X = 89.0


def _plain(df: pd.DataFrame) -> pd.DataFrame:
    """Nullable pandas dtypes -> float64 / object, so comparisons on missing values give False, not NA."""
    out = df.copy()
    for c in out.columns:
        dt = out[c].dtype
        if isinstance(dt, pd.BooleanDtype) or (pd.api.types.is_numeric_dtype(dt) and pd.api.types.is_extension_array_dtype(dt)):
            out[c] = out[c].astype("float64")
        elif pd.api.types.is_string_dtype(dt):
            out[c] = out[c].astype(object).where(out[c].notna(), None)
    return out


def attack_sign(ev: pd.DataFrame) -> pd.Series:
    """+1 if the event team attacks toward +x, -1 toward -x, NaN if unknown."""
    side = ev["home_defending_side"]
    known = ev["is_home_event"].notna()
    home = (ev["is_home_event"] == 1).to_numpy(bool)
    left, right = (side == "left").to_numpy(bool), (side == "right").to_numpy(bool)
    from_field = pd.Series(np.where((home & left) | (~home & right), 1.0, -1.0), index=ev.index)
    from_field = from_field.where(side.notna() & known)
    oz = ev[ev["type"].isin(UNBLOCKED) & (ev["zone_code"] == "O") & ev["x"].notna()]
    maj = (oz["x"] > 0).groupby([oz["game_id"], oz["period"], oz["event_team_id"]]).mean()
    keys = pd.MultiIndex.from_frame(ev[["game_id", "period", "event_team_id"]])
    frac = pd.Series(maj.reindex(keys).to_numpy(), index=ev.index)
    fallback = pd.Series(np.where(frac > 0.5, 1.0, -1.0), index=ev.index).where(frac.notna() & (frac != 0.5))
    return from_field.fillna(fallback)


def shot_features(events: pd.DataFrame) -> pd.DataFrame:
    """Feature rows for unblocked, non-shootout, non-penalty-shot attempts with coordinates."""
    ev = _plain(events[events["period_type"] != "SO"]).sort_values(["game_id", "sort_order"]).reset_index(drop=True)
    sign = attack_sign(ev)
    g = ev.groupby("game_id", sort=False)

    is_home = (ev["is_home_event"] == 1).to_numpy(bool)
    # running score before each event, from the event team's perspective
    goal = ev["type"] == "goal"
    known = ev["is_home_event"].notna().to_numpy(bool)
    hg = (goal & is_home & known).astype(int)
    ag = (goal & ~is_home & known).astype(int)
    home_before = hg.groupby(ev["game_id"]).cumsum() - hg
    away_before = ag.groupby(ev["game_id"]).cumsum() - ag

    prev_type = g["type"].shift(1)
    prev_team = g["event_team_id"].shift(1)
    prev_x, prev_y = g["x"].shift(1), g["y"].shift(1)
    dt = ev["t_game_s"] - g["t_game_s"].shift(1)
    same_period = ev["period"] == g["period"].shift(1)

    xn, yn = ev["x"] * sign, ev["y"] * sign
    dx = NET_X - xn
    own = np.where(is_home, ev["home_skaters"], ev["away_skaters"]).astype(float)
    opp = np.where(is_home, ev["away_skaters"], ev["home_skaters"]).astype(float)
    opp_goalie_in = np.where(is_home, ev["away_goalie_in"], ev["home_goalie_in"]).astype(float)

    f = pd.DataFrame(
        {
            "game_id": ev["game_id"],
            "event_id": ev["event_id"],
            "season": ev["game_id"] // 1000000 * 10001 + 1,  # 2023 -> 20232024
            "goal": goal.astype(int),
            "is_shot": ev["type"].isin(UNBLOCKED),
            "distance": np.hypot(dx, yn),
            "angle": np.degrees(np.arctan2(yn.abs(), dx)),
            "behind_net": (dx < 0).astype(int),
            "own_skaters": own,
            "opp_skaters": opp,
            "empty_net": (opp_goalie_in == 0).astype(int),
            "score_diff": np.where(is_home, home_before - away_before, away_before - home_before).clip(-3, 3),
            "is_home": is_home.astype(float),
            "period": ev["period"].clip(upper=4),
            "game_seconds": ev["t_game_s"],
            "dt_prev": dt.where(same_period).clip(upper=120),
            "prev_same_team": (prev_team == ev["event_team_id"]).astype(int),
            "prev_dist": np.hypot(ev["x"] - prev_x, ev["y"] - prev_y).where(same_period),
            "prev_xn": (prev_x * sign).where(same_period),
            "rebound": (prev_type.isin(ATTEMPTS) & (prev_team == ev["event_team_id"]) & (dt <= 3) & same_period).astype(int),
            "rush": (((prev_x * sign) < 25) & (dt <= 4) & same_period).astype(int),
            "shot_type": ev["shot_type"],
            "prev_type": prev_type,
        }
    )
    for t in SHOT_TYPES:
        f[f"st_{t}"] = (f["shot_type"] == t).astype(int)
    for t in PREV_TYPES:
        f[f"pt_{t}"] = (f["prev_type"] == t).astype(int)
    # own/opp >= 3 skaters drops penalty shots (situation 1 skater vs 0); empty-net shots are kept.
    keep = f["is_shot"] & ev["x"].notna() & sign.notna() & (own >= 3) & (opp >= 3)
    return f[keep].drop(columns=["is_shot", "shot_type", "prev_type"]).reset_index(drop=True)


def feature_cols(f: pd.DataFrame) -> list[str]:
    return [c for c in f.columns if c not in ("game_id", "event_id", "season", "goal")]


def fit_lgb(train: pd.DataFrame, params: dict[str, Any]) -> lgb.LGBMClassifier:
    m = lgb.LGBMClassifier(**params)
    m.fit(train[feature_cols(train)], train["goal"])
    return m


def fit_distance_baseline(train: pd.DataFrame) -> LogisticRegression:
    cols = ["distance", "angle", "empty_net"]
    m = LogisticRegression(max_iter=1000)
    m.fit(train[cols], train["goal"])
    m.cols_ = cols
    return m


def run(cfg: dict[str, Any]) -> pd.DataFrame:
    proc = repo_path(cfg["processed_dir"])
    seasons = sorted(int(p.stem) for p in (proc / "events").glob("*.parquet"))
    shots = {s: shot_features(pd.read_parquet(proc / "events" / f"{s}.parquet")) for s in seasons}
    out_dir = proc / "xg"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = []
    for s in seasons:
        train_seasons = [t for t in seasons if t < s][-cfg["train_window_seasons"]:] if cfg.get("train_window_seasons") else [t for t in seasons if t < s]
        if not train_seasons:
            continue
        train = pd.concat([shots[t] for t in train_seasons], ignore_index=True)
        test = shots[s]
        m = fit_lgb(train, cfg["lgb_params"])
        p = m.predict_proba(test[feature_cols(test)])[:, 1]
        b = fit_distance_baseline(train)
        pb = b.predict_proba(test[b.cols_])[:, 1]
        test.assign(xg=p)[["game_id", "event_id", "xg"]].to_parquet(out_dir / f"{s}.parquet", index=False)
        report.append(
            {
                "season": s,
                "train_seasons": f"{train_seasons[0]}-{train_seasons[-1]}",
                "n_train": len(train),
                "n_test": len(test),
                "goal_rate": test["goal"].mean(),
                "sum_xg_over_goals": p.sum() / test["goal"].sum(),
                "logloss_xg": log_loss(test["goal"], p),
                "logloss_distance_baseline": log_loss(test["goal"], pb),
                "logloss_constant": log_loss(test["goal"], np.full(len(test), train["goal"].mean())),
                "brier_xg": brier_score_loss(test["goal"], p),
            }
        )
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in report[-1].items()}, flush=True)
    rep = pd.DataFrame(report)
    res = repo_path("results")
    res.mkdir(exist_ok=True)
    rep.to_csv(res / "xg_eval.csv", index=False)
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/xg.yaml")
    args = ap.parse_args(argv)
    run(load_config(args.config))
    return 0


if __name__ == "__main__":
    sys.exit(main())
