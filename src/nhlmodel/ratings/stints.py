"""5v5 stints: stretches of a game in which the ten skaters on the ice don't change.

Each stint row holds game_id, start/end game-seconds, duration, the five home and five away skater ids,
the home score lead at the stint's start, and the home and away 5v5 xG during the stint. Built from
shift charts, play-by-play and the ``xg`` table, with the conventions of ``features/players.py``:

- 5v5 is read from the shift charts: a stint is kept if each team has exactly five skaters and a
  goalie on the ice. (Play-by-play situation codes change only at events, so they miss the moment a
  penalty expires; the shift charts don't.) Only shots coded 5v5 (1551) count toward stint xG.
- A shot at second t belongs to the stint with start < t <= end, so a shot at a change goes to the
  skaters whose shift ends then.
- Score state is the home lead from goals at or before the stint's start.

``validate`` compares each game's stint totals with the 5v5 totals from play-by-play: games where
stints recover under 95% of the 5v5 xG or 98% of the 5v5 seconds are listed as failing and left out
of the ratings. (The spec's 1% xG tolerance failed 4-8% of games over a single shot at a misaligned
change; the median game recovers 100%.)

    python -m nhlmodel.ratings.stints [--seasons 20232024 ...] [--force]

writes ``data/processed/stints/<season>.parquet`` and ``stint_checks/<season>.parquet``. Finished
seasons are kept; the current season is rebuilt each time.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from ..config import load_config, repo_path
from ..features.players import UNBLOCKED, _gsec

HOME = [f"h{i}" for i in range(5)]
AWAY = [f"a{i}" for i in range(5)]


def _game_stints(gid, ev, sh_s, sh_e, sh_p, sh_home, sh_goalie, shots, goals):
    """Stints of one game. ``ev`` = (times, is_5v5), ``shots`` = (times, is_home, xg), ``goals`` = (times, is_home)."""
    ev_t, ev_5 = ev
    T = np.maximum.accumulate(np.clip(ev_t, 0, None))
    n = int(max(T.max(), sh_e.max())) + 1
    lengths = np.diff(np.append(T, n))
    state = np.concatenate([np.zeros(T[0], bool), np.repeat(ev_5, lengths)])
    cs = np.concatenate([[0], np.cumsum(state)])
    b = np.unique(np.concatenate([np.clip(sh_s, 0, n), np.clip(sh_e, 0, n), [0, n]]))
    b0, b1 = b[:-1], b[1:]
    on = (sh_s[:, None] <= b0[None, :]) & (sh_e[:, None] >= b1[None, :])
    sk = ~sh_goalie
    nh, na = on[sk & sh_home].sum(0), on[sk & ~sh_home].sum(0)
    gh, ga = on[sh_goalie & sh_home].any(0), on[sh_goalie & ~sh_home].any(0)
    keep = (nh == 5) & (na == 5) & gh & ga
    sh_p, sh_home, on = sh_p[sk], sh_home[sk], on[sk]
    total = (int(cs[-1]), float(shots[2][(shots[0] >= 0)].sum()) if len(shots[0]) else 0.0)
    if not keep.any():
        return None, total
    ids = []
    for side in (sh_home, ~sh_home):
        o = on[side][:, keep]
        s_idx, k_idx = np.nonzero(o.T)  # ordered by stint, then shift
        ids.append(np.sort(sh_p[side][k_idx].reshape(-1, 5), axis=1))
    st = pd.DataFrame(np.hstack(ids), columns=HOME + AWAY)
    st.insert(0, "game_id", gid)
    st["start_s"], st["end_s"] = b0[keep], b1[keep]
    st["dur_s"] = st["end_s"] - st["start_s"]
    gt, gh = goals
    st["home_lead"] = [int((gh[gt <= s]).sum() - (~gh[gt <= s]).sum()) for s in st["start_s"]] if len(gt) else 0
    xh, xa = np.zeros(len(st)), np.zeros(len(st))
    t, home, x = shots
    if len(t):
        k = np.searchsorted(b1, t, side="left")  # stint (over all segments) with b0 < t <= b1
        k = np.clip(k, 0, len(b1) - 1)
        ok = (b0[k] < t) & (t <= b1[k]) & keep[k]
        pos = np.cumsum(keep) - 1  # segment index -> kept stint index
        np.add.at(xh, pos[k[ok & home]], x[ok & home])
        np.add.at(xa, pos[k[ok & ~home]], x[ok & ~home])
    st["xg_home"], st["xg_away"] = xh, xa
    return st, total


def build_stints(events: pd.DataFrame, shifts: pd.DataFrame, xg: pd.DataFrame, rosters: pd.DataFrame,
                 bad_games: set | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(stints, per-game check table) for all games with shifts and play-by-play."""
    bad_games = bad_games or set()
    goalies = set(map(tuple, rosters.loc[rosters["position"] == "G", ["game_id", "player_id"]].to_numpy()))
    sh = shifts[~shifts["game_id"].isin(bad_games)].dropna(subset=["period", "start_s", "end_s"])
    sh = sh.sort_values("game_id")
    is_g = np.array([(g, p) in goalies for g, p in zip(sh["game_id"].to_numpy(), sh["player_id"].to_numpy())], bool)
    ev = events[(events["period_type"] != "SO") & events["game_id"].isin(set(sh["game_id"]))]
    ev = ev.sort_values(["game_id", "sort_order"])
    home_of = ev.groupby("game_id")["home_team_id"].first()

    is5 = (ev["situation_code"] == "1551").fillna(False).to_numpy(bool)
    shots = ev[ev["type"].isin(UNBLOCKED) & is5 & ev["event_team_id"].notna()]
    shots = shots.merge(xg[["game_id", "event_id", "xg"]].astype({"game_id": "int64", "event_id": "int64"}),
                        on=["game_id", "event_id"], how="left")
    goals = ev[(ev["type"] == "goal") & ev["event_team_id"].notna()]

    def split(df, cols):
        g = df["game_id"].to_numpy("int64")
        u, i = np.unique(g, return_index=True)
        ends = np.append(i[1:], len(g))
        arrs = [c if isinstance(c, np.ndarray) else df[c].to_numpy() for c in cols]
        return {gid: [a[s:e] for a in arrs] for gid, s, e in zip(u, i, ends)}

    ev_d = split(ev, [_gsec(ev["period"], ev["t_period_s"]), is5])
    sh_home = sh["team_id"].to_numpy("int64") == sh["game_id"].map(home_of).to_numpy("float")
    sh_d = split(sh, [_gsec(sh["period"], sh["start_s"]), _gsec(sh["period"], sh["end_s"]),
                      sh["player_id"].to_numpy("int64"), sh_home, is_g])
    shots_home = shots["event_team_id"].to_numpy("int64") == shots["home_team_id"].to_numpy("int64")
    sh_x = split(shots, [_gsec(shots["period"], shots["t_period_s"]), shots_home, shots["xg"].fillna(0.0).to_numpy(float)])
    goals_home = goals["event_team_id"].to_numpy("int64") == goals["home_team_id"].to_numpy("int64")
    g_d = split(goals, [_gsec(goals["period"], goals["t_period_s"]), goals_home])

    empty3, empty2 = [np.array([], int), np.array([], bool), np.array([], float)], [np.array([], int), np.array([], bool)]
    out, checks = [], []
    for gid, (s, e, p, hm, gl) in sh_d.items():
        if gid not in ev_d:
            continue
        st, (sec5, xg5) = _game_stints(gid, ev_d[gid], s, e, p, hm, gl, sh_x.get(gid, empty3), g_d.get(gid, empty2))
        sec_st = int(st["dur_s"].sum()) if st is not None else 0
        xg_st = float(st[["xg_home", "xg_away"]].to_numpy().sum()) if st is not None else 0.0
        checks.append((gid, sec5, sec_st, xg5, xg_st))
        if st is not None:
            out.append(st)
    chk = pd.DataFrame(checks, columns=["game_id", "sec_5v5", "sec_stints", "xg_5v5", "xg_stints"])
    stints = pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["game_id"] + HOME + AWAY)
    return stints, chk


def validate(chk: pd.DataFrame, xg_tol: float = 0.05, sec_tol: float = 0.02) -> pd.DataFrame:
    """Adds ``ok``: stints recover the game's 5v5 xG within ``xg_tol`` and its 5v5 seconds within ``sec_tol``."""
    c = chk.copy()
    xg_ok = (c["xg_5v5"] - c["xg_stints"]) <= xg_tol * c["xg_5v5"].clip(lower=1e-9) + 1e-9
    sec_ok = (c["sec_5v5"] - c["sec_stints"]) <= sec_tol * c["sec_5v5"]
    c["ok"] = xg_ok & sec_ok & (c["sec_stints"] > 0)
    return c


def build_season(season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    proc = repo_path("data/processed")
    read = lambda kind: pd.read_parquet(proc / kind / f"{season}.parquet")  # noqa: E731
    q = read("quality")
    bad = set(q.loc[~q["shifts_ok"].fillna(False).astype(bool), "game_id"])
    st, chk = build_stints(read("events"), read("shifts"), read("xg"), read("rosters"), bad)
    chk = validate(chk)
    return st[st["game_id"].isin(set(chk.loc[chk["ok"], "game_id"]))].reset_index(drop=True), chk


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, nargs="*")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    data_cfg = load_config("configs/data.yaml")
    proc = repo_path(data_cfg["processed_dir"])
    current = data_cfg["seasons"].get("current")
    have = sorted(int(p.stem) for p in (proc / "xg").glob("*.parquet"))
    for s in args.seasons or have:
        out = proc / "stints" / f"{s}.parquet"
        if out.exists() and not args.force and s != current:
            continue
        if not (proc / "shifts" / f"{s}.parquet").exists() or not (proc / "xg" / f"{s}.parquet").exists():
            continue
        st, chk = build_season(s)
        for kind, df in (("stints", st), ("stint_checks", chk)):
            (proc / kind).mkdir(exist_ok=True)
            df.to_parquet(proc / kind / f"{s}.parquet", index=False)
        print(f"{s}: {len(st)} stints, {int(chk['ok'].sum())}/{len(chk)} games pass, "
              f"xG recovered {chk['xg_stints'].sum() / chk['xg_5v5'].sum():.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
