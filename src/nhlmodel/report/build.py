"""Build and serve the front end (a retro game-menu page of the project's results).

    python -m nhlmodel.report build          # -> site/index.html (self-contained)
    python -m nhlmodel.report serve [--port 8000]   # build, then serve on 127.0.0.1 only

The page shows only numbers read from files on disk (processed tables, results/). Sections whose
inputs don't exist yet say so instead of showing placeholder values. Every metric carries the
split it was computed on.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import load_config, repo_path

TEMPLATE = Path(__file__).with_name("template.html")


def _season_label(s: int) -> str:
    return f"{s // 10000}-{str(s % 10000)[2:]}"


def data_status(cfg) -> dict:
    proc, raw = repo_path(cfg["processed_dir"]), repo_path(cfg["raw_dir"])
    games = pd.read_parquet(proc / "games.parquet")
    rows = []
    for s, g in games.groupby("season"):
        y = s // 10000
        q_path = proc / "quality" / f"{s}.parquet"
        row = {
            "season": int(s), "label": _season_label(int(s)), "games": int(len(g)),
            "home_win_rate": round(float(g["home_win"].mean()), 4),
            "pbp_downloaded": len(list((raw / "nhl_web/pbp" / str(y)).glob("*.json.gz"))) if (raw / "nhl_web/pbp" / str(y)).exists() else 0,
            "shifts_downloaded": len(list((raw / "nhl_stats/shifts" / str(y)).glob("*.json.gz"))) if (raw / "nhl_stats/shifts" / str(y)).exists() else 0,
            "processed": q_path.exists(),
        }
        if q_path.exists():
            q = pd.read_parquet(q_path)
            # the quality table records what was downloaded, so builds without the raw cache still count it
            row["pbp_downloaded"] = max(row["pbp_downloaded"], int(q["has_pbp"].astype(bool).sum()))
            row["shifts_downloaded"] = max(row["shifts_downloaded"], int(q["has_shifts"].astype(bool).sum()))
            row.update({
                "goals_match": round(float(q["pbp_goals_match"].astype(float).mean()), 4),
                "two_starters": round(float((q["n_starters"] == 2).mean()), 4),
                "shifts_ok": round(float(q["shifts_ok"].astype(float).mean()), 4),
                "shifts_flagged": int((~q["shifts_ok"].astype(bool)).sum()),
                "shots_xy_per_game": round(float(q["n_unblocked_with_xy"].mean()), 1),
            })
        rows.append(row)
    return {"seasons": rows, "total_games": int(len(games))}


# Plain-language names for the runs a visitor should see first. kind: "main" (shown by default),
# "upper" (uses information only known at puck drop: an upper bound, never a usable model),
# "detail" (tuning and diagnostic runs, behind a toggle).
RUN_INFO = {
    "baseline_a": ("Always pick the home team", "Gives every game the league's usual home win chance. The bar to clear.", "main"),
    "baseline_b": ("Simple model", "Five inputs: shot quality, starting goalie, rest days, home ice.", "main"),
    "baseline_b_leaky_actual": ("Simple model, real goalie", "Uses the goalie who actually started, which is only certain at puck drop.", "upper"),
    "p3_logreg_C0.001": ("Full model", "The simple model's method, given all ~140 stats we track.", "main"),
    "p3_rf_leaf200_sqrt": ("Random forest", "A tree-based machine-learning model on the same ~140 stats.", "main"),
    "p3_lgbm_l2_lr0.02_n300": ("Gradient boosting", "Another tree-based machine-learning model on the same stats.", "main"),
    "adj_b_sa": ("Simple model + score-adjusted shots", "Discounts shots by teams that were trailing (they shoot more).", "main"),
    "lu_b": ("Simple model + expected lineup", "Adds ratings of the players expected to dress (those who played the previous game).", "main"),
    "lu_b_leaky": ("Simple model + real lineup", "Uses the lineup that actually played, which is only certain at puck drop.", "upper"),
    "lu_logreg_full_C0.001": ("Full model + expected lineup", "All ~140 stats plus ratings of the players expected to dress.", "main"),
    "rp_b": ("Simple model + adjusted player ratings", "Rates each expected player for the chances their team creates and allows with them on the ice, adjusted for teammates and opponents.", "main"),
    "rp_b_leaky": ("Simple model + real lineup's adjusted ratings", "Same, with the lineup that actually played, which is only certain at puck drop.", "upper"),
    "rp_logreg_full_C0.001": ("Full model + adjusted player ratings", "The full model with expected lineup, plus the adjusted player ratings. This is the live model.", "main"),
}
_DETAIL_PREFIX = {
    "baseline_b_C": "Simple model, tuning",
    "baseline_b_abl_no_": "Simple model without",
    "baseline_b_projected": "Simple model, projected goalie",
    "p3_logreg": "Full model, tuning",
    "p3_rf": "Random forest, tuning",
    "p3_lgbm": "Gradient boosting, tuning",
    "adj_": "Score/arena adjustment check",
    "lu_": "Player lineup check",
    "rp_": "Adjusted player ratings check",
}


def run_info(experiment: str) -> dict:
    if experiment in RUN_INFO:
        name, what, kind = RUN_INFO[experiment]
    else:
        prefix = next((p for p in _DETAIL_PREFIX if experiment.startswith(p)), None)
        name = f"{_DETAIL_PREFIX[prefix]} ({experiment})" if prefix else experiment
        what, kind = "Tuning or diagnostic run.", "detail"
    if "leaky" in experiment and kind != "upper":
        kind = "upper"
    return {"name": name, "what": what, "kind": kind}


def experiments() -> dict | None:
    """Latest logged row per run (the log is append-only, so reruns keep their history)."""
    p = repo_path("results/experiments.csv")
    if not p.exists():
        return None
    df = pd.read_csv(p).drop_duplicates("run_id", keep="last")
    keep = ["run_id", "experiment", "period", "seasons", "split", "model", "feature_groups", "goalie_variant",
            "n_games", "log_loss", "log_loss_lo", "log_loss_hi", "brier", "ece", "accuracy", "log_loss_excl_2020_21",
            "notes", "date_run"]
    df = df[keep].fillna("")
    rows = df.to_dict(orient="records")
    for r in rows:
        r.update(run_info(r["experiment"]))
    return {"rows": rows}


BEST_TEST_RUN = "rp_logreg_full_C0.001__test"  # the deployable model's held-out predictions


def _ll(y, p) -> float:
    import numpy as np
    p = np.clip(np.asarray(p, float), 1e-15, 1 - 1e-15)
    y = np.asarray(y, float)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def _record(df: pd.DataFrame) -> dict | None:
    """Winner-pick rate and prediction error for rows with p (P(home win)) and home_win."""
    if df.empty:
        return None
    y, p = df["home_win"].astype(int), df["p"].astype(float)
    return {"n": int(len(df)), "accuracy": round(float(((p >= 0.5) == (y == 1)).mean()), 4),  # same rule as the page
            "log_loss": round(_ll(y, p), 4), "home_rate": round(float(y.mean()), 4)}


# Model inputs -> plain language for the per-game explainer. Per-side stats are "<window>_<stat>".
_WINDOWS = {"l5": "last 5 games", "l10": "last 10 games", "l20": "last 20 games", "ewm5": "last ~5 games, weighted",
            "ewm15": "last ~15 games, weighted", "std": "this season"}
_SHARES = {"xg": "xG share", "xg_5v5": "5-on-5 xG share", "corsi": "shot attempt share",
           "corsi_5v5": "5-on-5 shot attempt share", "fenwick": "unblocked attempt share",
           "fenwick_5v5": "5-on-5 unblocked attempt share", "sog": "shots on goal share", "goals": "goal share",
           "goals_5v5": "5-on-5 goal share", "raw_corsi_5v5": "5-on-5 shot attempt share, unshrunk"}
_RATES = {"goals_for_pg": "goals per game", "goals_against_pg": "goals allowed per game",
          "sog_for_pg": "shots per game", "sog_against_pg": "shots allowed per game",
          "pp_goals_for_pg": "power-play goals per game", "pp_goals_against_pg": "power-play goals allowed per game",
          "sh_goals_for_pg": "shorthanded goals per game", "sh_goals_against_pg": "shorthanded goals allowed per game",
          "penalties_for_pg": "penalties taken per game", "penalties_against_pg": "penalties drawn per game",
          "pp_goals_for_per60": "power-play goals per 60 PP minutes",
          "pp_goals_against_per60": "goals allowed per 60 PK minutes"}
_SINGLE = {  # name -> (group, label, format)
    "expected_goalie_gsax100_ewm": ("Goaltending", "starting goalie: saves above expected per 100 shots, recent", "signed2"),
    "expected_goalie_gsax100_season": ("Goaltending", "starting goalie: saves above expected per 100 shots, season", "signed2"),
    "expected_goalie_gsax100_career": ("Goaltending", "starting goalie: saves above expected per 100 shots, career", "signed2"),
    "expected_goalie_shots_career": ("Goaltending", "starting goalie: career shots faced", "int"),
    "lineup_on_xg_share": ("Players in the lineup", "dressed skaters' on-ice xG share", "pct"),
    "lineup_rel_xg_share": ("Players in the lineup", "dressed skaters' xG share vs teammates", "pp"),
    "lineup_missing_toi_share": ("Players in the lineup", "regulars missing (share of ice time)", "pct"),
    "rapm_off": ("Players in the lineup", "lineup's adjusted offense rating (xG/60 created above average)", "signed2"),
    "rapm_def": ("Players in the lineup", "lineup's adjusted defense rating (xG/60 prevented above average)", "signed2"),
    "rapm_net": ("Players in the lineup", "lineup's adjusted overall rating (offense + defense)", "signed2"),
    "rest_days": ("Rest and schedule", "days of rest", "int"),
    "back_to_back": ("Rest and schedule", "played yesterday", "yesno"),
    "season_opener": ("Rest and schedule", "season opener", "yesno"),
    "games_last_7d": ("Rest and schedule", "games in the last 7 days", "int"),
    "tz_change_h": ("Rest and schedule", "time zones moved since last game", "signed1"),
    "games_played_season": ("Rest and schedule", "games played this season", "int"),
}
_CONTEXT = {"neutral_site": ("Rest and schedule", "neutral site", "yesno")}


def term_label(term: str) -> tuple[str, str, str]:
    """(group, label, value format) for a design column of the full model."""
    if term in _CONTEXT:
        return _CONTEXT[term]
    name = term.removeprefix("d_")
    if name in _SINGLE:
        return _SINGLE[name]
    win, _, stat = name.partition("_")
    when = _WINDOWS.get(win, win)
    if stat.endswith("_share") and stat[:-6] in _SHARES:
        base = stat[:-6]
        group = ("Shot quality (xG)" if "xg" in base else "Goals" if "goals" in base else "Shot volume")
        return group, f"{_SHARES[base]}, {when}", "pct"
    if stat in _RATES:
        group = ("Special teams" if stat.startswith(("pp_", "sh_", "penalties")) else
                 "Goals" if stat.startswith("goals") else "Shot volume")
        return group, f"{_RATES[stat]}, {when}", "num1" if stat.endswith("per60") else "num2"
    return "Other stats", name.replace("_", " "), "num2"


# Season stage (each team's games played) goes into the starting point rather than the drivers.
_BASE_TERMS = ("intercept", "home_games_played_season", "away_games_played_season")


def explain(terms: pd.DataFrame, p_home: float, top: int = 8) -> dict | None:
    """Why one game's prediction is what it is (terms from ``models.families.explain_family``).

    ``base``: the home win chance if the two teams were even on every input (home ice and season stage
    only). Each group's and each of the ``top`` biggest single inputs' ``pts``: the home team's win chance
    minus what it would be with no home-minus-away difference in that input (or group), in percentage
    points; positive favors the home team."""
    import numpy as np

    def sig(z: float) -> float:
        return float(1 / (1 + np.exp(-z)))

    def num(v) -> float | None:
        return None if pd.isna(v) else round(float(v), 4)

    total = float(terms["logit"].sum())
    if abs(sig(total) - p_home) > 1e-4:  # terms from a different fit than the prediction
        return None
    t = terms[~terms["term"].isin(_BASE_TERMS)].copy()
    lab = t["term"].map(term_label)
    t["group"], t["label"], t["fmt"] = lab.str[0], lab.str[1], lab.str[2]
    groups = t.groupby("group")["logit"].sum()
    n_inputs = int(len(t))
    out_groups = [{"name": g, "pts": round(100 * (p_home - sig(total - v)), 2)} for g, v in groups.items()]
    t = t.reindex(t["logit"].abs().sort_values(ascending=False).index).head(top)
    return {"base": round(sig(float(terms.loc[terms["term"].isin(_BASE_TERMS), "logit"].sum())), 4),
            "groups": sorted(out_groups, key=lambda g: -abs(g["pts"])),
            "top": [{"label": r.label, "group": r.group, "fmt": r.fmt, "home": num(r.home), "away": num(r.away),
                     "pts": round(100 * (p_home - sig(total - r.logit)), 2)} for r in t.itertuples()],
            "n_inputs": n_inputs}


def live(cfg) -> dict | None:
    """Upcoming-game predictions and this season's record (files written by ``python -m nhlmodel.live``)."""
    proc = repo_path(cfg["processed_dir"])
    up_path = proc / "predictions_upcoming.parquet"
    if not up_path.exists():
        return None
    up = pd.read_parquet(up_path)
    season = cfg["seasons"].get("current")
    games = pd.read_parquet(proc / "games.parquet")
    feats = pd.read_parquet(proc / "features.parquet", columns=[
        "game_id", "home_rest_days", "away_rest_days", "home_back_to_back", "away_back_to_back"])
    ep = proc / "explain_upcoming.parquet"
    terms = pd.read_parquet(ep) if ep.exists() else pd.DataFrame(columns=["game_id"])
    by_game = dict(tuple(terms.groupby("game_id")))
    rows = []
    for r in up.merge(feats, on="game_id", how="left").itertuples():
        why = explain(by_game[r.game_id], float(r.p_home)) if r.game_id in by_game else None
        rows.append({"game_id": int(r.game_id), "start_utc": r.start_time_utc.isoformat(), "date": str(r.local_date),
                     "away": r.away_abbrev, "home": r.home_abbrev, "p_home": round(float(r.p_home), 4),
                     "lineup": r.lineup, "home_b2b": bool(r.home_back_to_back == 1), "away_b2b": bool(r.away_back_to_back == 1),
                     "why": why})
    out = {"updated_at": str(up["made_at"].iloc[0]) if "made_at" in up and len(up) else None,
           "season": int(season) if season else None, "label": _season_label(int(season)) if season else None,
           "upcoming": rows, "season_record": None, "live_record": None, "recent": []}
    meta = games[["game_id", "local_date", "away_abbrev", "home_abbrev", "home_win"]]
    sp = proc / "predictions_season.parquet"
    if sp.exists():
        done = pd.read_parquet(sp).merge(meta, on="game_id").sort_values(["local_date", "game_id"])
        out["season_record"] = _record(done)
        out["recent"] = [{"date": str(r.local_date), "away": r.away_abbrev, "home": r.home_abbrev,
                          "p_home": round(float(r.p), 4), "home_win": int(r.home_win)} for r in done.tail(12).itertuples()][::-1]
    lp = proc / "predictions_log.csv"
    if lp.exists():
        log = pd.read_csv(lp).rename(columns={"p_home": "p"}).merge(meta, on="game_id")
        out["live_record"] = _record(log)
    return out


def explorer(cfg) -> dict | None:
    """Every graded game: held-out test seasons plus this season so far, as compact rows."""
    proc = repo_path(cfg["processed_dir"])
    parts = []
    tp = repo_path(f"results/predictions/{BEST_TEST_RUN}.parquet")
    if tp.exists():
        parts.append(pd.read_parquet(tp)[["game_id", "p"]])
    sp = proc / "predictions_season.parquet"
    if sp.exists():
        parts.append(pd.read_parquet(sp)[["game_id", "p"]])
    if not parts:
        return None
    games = pd.read_parquet(proc / "games.parquet")[["game_id", "season", "local_date", "away_abbrev", "home_abbrev",
                                                      "away_score", "home_score", "home_win"]]
    df = pd.concat(parts).drop_duplicates("game_id", keep="last").merge(games, on="game_id").sort_values("game_id")
    return {"cols": ["date", "season", "away", "home", "p_home", "home_win", "score"],
            "rows": [[str(r.local_date), int(r.season), r.away_abbrev, r.home_abbrev, round(float(r.p), 4), int(r.home_win),
                      f"{int(r.away_score)}-{int(r.home_score)}"] for r in df.itertuples()]}


def git_rev() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_path("."), capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def build(cfg, out: Path) -> Path:
    payload = {
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "git_rev": git_rev(),
        "data": data_status(cfg),
        "experiments": experiments(),
        "live": live(cfg),
        "predictions": explorer(cfg),
    }
    blob = json.dumps(payload).replace("</", "<\\/")  # safe inside <script>
    html = TEMPLATE.read_text().replace("/*__DATA__*/null", blob)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html)
    return out / "index.html"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "serve"])
    ap.add_argument("--config", default="configs/data.yaml")
    ap.add_argument("--out", default="site")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)
    out = repo_path(args.out)
    path = build(load_config(args.config), out)
    print(f"wrote {path}")
    if args.cmd == "serve":
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
        with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as srv:
            print(f"serving on http://127.0.0.1:{args.port}/  (Ctrl+C to stop)")
            srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
