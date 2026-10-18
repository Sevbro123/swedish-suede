"""Build and serve the local retro-terminal front end.

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


def _train_label(span: str) -> str:
    """'20222023-20232024' -> '2022-23 -> 2023-24'; a single season -> '2022-23'."""
    a, b = (_season_label(int(x)) for x in span.split("-"))
    return a if a == b else f"{a} -> {b}"


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
            row.update({
                "goals_match": round(float(q["pbp_goals_match"].astype(float).mean()), 4),
                "two_starters": round(float((q["n_starters"] == 2).mean()), 4),
                "shifts_ok": round(float(q["shifts_ok"].astype(float).mean()), 4),
                "shifts_flagged": int((~q["shifts_ok"].astype(bool)).sum()),
                "shots_xy_per_game": round(float(q["n_unblocked_with_xy"].mean()), 1),
            })
        rows.append(row)
    return {"seasons": rows, "total_games": int(len(games))}


def xg_eval() -> dict | None:
    p = repo_path("results/xg_eval.csv")
    if not p.exists():
        return None
    df = pd.read_csv(p)
    return {
        "split": "held-out season S; model trained only on seasons before S",
        "rows": [
            {"season": int(r.season), "label": _season_label(int(r.season)), "train": _train_label(r.train_seasons),
             "n_test": int(r.n_test), "xg": round(r.logloss_xg, 4), "distance": round(r.logloss_distance_baseline, 4),
             "constant": round(r.logloss_constant, 4), "xg_over_goals": round(r.sum_xg_over_goals, 3)}
            for r in df.itertuples()
        ],
        "modified": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def experiments() -> dict | None:
    p = repo_path("results/experiments.csv")
    return None if not p.exists() else {"rows": pd.read_csv(p).to_dict(orient="records")}


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
        "xg": xg_eval(),
        "experiments": experiments(),
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
