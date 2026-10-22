"""Recent form ("hot streaks"): how far skaters, goalies and the team have run above their own norm lately.

Every form feature is *recent minus baseline*, so it measures a heater on top of what the slower
ratings (RAPM, career GSAx, season-to-date team stats) already carry.

Skaters, per skater-game (all situations, shootouts excluded, empty-net goals excluded):
- ``pts`` = goals + primary/secondary assists, ``goals``, ``ixg`` = xG of the player's own unblocked shots
- form over the last N games = sum(stat) - N_played * baseline, divided by N, where baseline is the
  player's exponentially weighted per-game rate (``baseline_halflife_games``, across seasons) shrunk toward
  the league per-game rate for his position (F / D) with ``baseline_pseudo_games`` pseudo-games
- team feature ``form_{stat}_l{N}``: summed over the lineup (projected = previous game's skaters,
  ``leaky_`` = the game's own roster), so it reads "lineup's points per game above its norm, lately"

Goalies, per goalie appearance: league-relative GSAx (as in ``goalies.py``) over his last N appearances,
per 100 shots, shrunk toward 0 with ``goalie_recent_pseudo_shots``, minus his career GSAx/100 (shrunk with
``goalies.prior_shots``). ``form_goalie_l{N}`` is the P(start)-weighted average over the pre-game starter
model's candidates; ``leaky_form_goalie_l{N}`` uses the actual starter.

Team: ``form_win_l{N}`` = wins in the franchise's last N games (OT/SO included) / N, minus 0.5;
``form_streak`` = current run of consecutive wins (+) or losses (-), capped at +-5.

As-of rule: every state is the one after the player's / team's last game that started strictly before G.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .asof import franchise_ids
from .goalies import league_offset, starter_candidates, starter_probabilities

SKATER_STATS = ["pts", "goals", "ixg"]
UNBLOCKED = ["goal", "shot-on-goal", "missed-shot"]


def skater_games(events: pd.DataFrame, xg: pd.DataFrame, rosters: pd.DataFrame) -> pd.DataFrame:
    """One row per dressed skater-game: pts, goals, ixg (0 when he did nothing)."""
    ev = events[(events["period_type"] != "SO") & events["type"].isin(UNBLOCKED)]
    ev = ev[["game_id", "event_id", "type", "shooter_id", "assist1_id", "assist2_id"]].merge(
        xg[["game_id", "event_id", "xg", "empty_net"]].astype({"game_id": "int64", "event_id": "int64"}),
        on=["game_id", "event_id"], how="left")
    ev = ev[ev["empty_net"].fillna(0) == 0]
    goals = ev[ev["type"] == "goal"]
    parts = [
        goals[["game_id", "shooter_id"]].rename(columns={"shooter_id": "player_id"}).assign(goals=1.0, pts=1.0),
        goals[["game_id", "assist1_id"]].rename(columns={"assist1_id": "player_id"}).assign(pts=1.0),
        goals[["game_id", "assist2_id"]].rename(columns={"assist2_id": "player_id"}).assign(pts=1.0),
        ev[["game_id", "shooter_id", "xg"]].rename(columns={"shooter_id": "player_id", "xg": "ixg"}),
    ]
    s = pd.concat(parts, ignore_index=True).dropna(subset=["player_id"])
    s["player_id"] = s["player_id"].astype("int64")
    s["game_id"] = s["game_id"].astype("int64")
    s = s.groupby(["game_id", "player_id"])[SKATER_STATS].sum(min_count=0)
    sk = rosters.loc[rosters["position"] != "G", ["game_id", "team_id", "player_id", "position"]].copy()
    sk = sk.astype({"game_id": "int64", "team_id": "int64", "player_id": "int64"})
    sk["pos"] = np.where(sk["position"] == "D", "D", "F")
    out = sk.merge(s.reset_index(), on=["game_id", "player_id"], how="left")
    out[SKATER_STATS] = out[SKATER_STATS].fillna(0.0)
    return out.drop(columns=["position"])


def _league_rate_asof(df: pd.DataFrame, cols: list[str], by: str) -> pd.DataFrame:
    """Per row: mean of ``cols`` over rows of the same ``by`` group that started strictly earlier."""
    out = pd.DataFrame(np.nan, index=df.index, columns=cols)
    for _, d in df.groupby(by):
        d = d.sort_values("start_time_utc")
        t = d["start_time_utc"].to_numpy()
        idx = np.searchsorted(t, t, side="left") - 1
        cums = d[cols].cumsum().to_numpy()
        ok = idx >= 0
        vals = np.full((len(d), len(cols)), np.nan)
        vals[ok] = cums[idx[ok]] / (idx[ok] + 1)[:, None]
        out.loc[d.index] = vals
    return out


def skater_states(sg: pd.DataFrame, games: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Per skater-game: form over the last N games *after* that game (look it up strictly before G)."""
    p = sg.merge(games[["game_id", "start_time_utc"]], on="game_id", how="left")
    p = p.sort_values(["player_id", "start_time_utc"]).reset_index(drop=True)
    league = _league_rate_asof(p, SKATER_STATS, "pos").fillna(0.0)
    grp = p.groupby("player_id", sort=False)
    h, k = cfg["baseline_halflife_games"], cfg["baseline_pseudo_games"]
    lam = 0.5 ** (1 / h)
    n = grp.cumcount().to_numpy() + 1
    count = (1 - lam ** n) / (1 - lam)  # decayed number of games
    out = p[["player_id", "start_time_utc"]].copy()
    for c in SKATER_STATS:
        dec_sum = grp[c].transform(lambda s: s.ewm(halflife=h).mean()).to_numpy() * count
        base = (dec_sum + k * league[c].to_numpy()) / (count + k)
        for w in cfg["windows"]:
            recent = grp[c].transform(lambda s: s.rolling(w, min_periods=1).sum()).to_numpy()
            played = np.minimum(n, w)
            out[f"{c}_l{w}"] = (recent - played * base) / w
    return out


def _lookup(queries: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame:
    q = queries.sort_values("start_time_utc")
    s = states.rename(columns={"start_time_utc": "state_time"}).sort_values("state_time")
    return pd.merge_asof(q, s, left_on="start_time_utc", right_on="state_time", by="player_id",
                         allow_exact_matches=False, direction="backward").drop(columns=["state_time"])


def skater_form(members: pd.DataFrame, sg: pd.DataFrame, games: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Per (game_id, team_id): lineup sums of skater form, projected and ``leaky_`` actual.

    ``members``: ``players.lineup_members`` output (proj / actual flags per team-game and skater)."""
    st = skater_states(sg, games, cfg)
    q = members[["game_id", "team_id", "start_time_utc", "player_id", "proj", "actual"]].copy()
    q["player_id"] = q["player_id"].astype("int64")
    m = _lookup(q, st)
    cols = [c for c in st.columns if c not in ("player_id", "start_time_utc")]
    m[cols] = m[cols].fillna(0.0)  # no history: at his norm
    keys = members[["game_id", "team_id"]].drop_duplicates().set_index(["game_id", "team_id"])
    out = keys.copy()
    for flag, prefix in (("proj", ""), ("actual", "leaky_")):
        L = m[m[flag]]
        agg = L.groupby(["game_id", "team_id"])[cols].sum()
        for c in cols:
            out[f"{prefix}form_{c}"] = agg[c].reindex(out.index).fillna(0.0)
    return out.reset_index()


def goalie_form(gg: pd.DataFrame, games: pd.DataFrame, gcfg: dict[str, Any], cfg: dict[str, Any]) -> pd.DataFrame:
    """Per (game_id, team_id): expected starter's recent GSAx/100 minus career, and the ``leaky_`` actual starter's.

    ``gg``: ``goalies.goalie_games_with_xg`` output."""
    gg = gg.reset_index(drop=True)
    gsax = gg["xga"] - gg["ga"]
    if gcfg.get("league_relative", True):
        gsax = gsax - gg["shots"] * league_offset(gg, gcfg.get("league_prior_shots", 5000))
    p = gg["player_id"]
    st = gg[["player_id", "start_time_utc"]].copy()
    k_c, k_r = gcfg["prior_shots"], cfg["goalie_recent_pseudo_shots"]
    career = 100 * gsax.groupby(p).cumsum() / (gg["shots"].groupby(p).cumsum() + k_c)
    cols = []
    for w in cfg["goalie_windows"]:
        rg = gsax.groupby(p).transform(lambda s: s.rolling(w, min_periods=1).sum())
        rs = gg["shots"].groupby(p).transform(lambda s: s.rolling(w, min_periods=1).sum())
        st[f"goalie_l{w}"] = 100 * rg / (rs + k_r) - career
        cols.append(f"goalie_l{w}")
    st["player_id"] = st["player_id"].astype("int64")

    sched = games[["game_id", "season", "start_time_utc"]]
    cands = starter_probabilities(starter_candidates(gg, games, gcfg["candidate_pool_games"]), gcfg.get("seed", 0))
    cands = cands.merge(sched.drop(columns="season"), on="game_id", how="left")
    cands["player_id"] = cands["player_id"].astype("int64")
    c = _lookup(cands[["game_id", "team_id", "start_time_utc", "player_id", "p_start"]], st)
    c[cols] = c[cols].fillna(0.0)
    exp = c[cols].mul(c["p_start"], axis=0).groupby([c["game_id"], c["team_id"]]).sum()
    exp.columns = [f"form_{x}" for x in cols]

    act = gg[gg["starter"].astype(bool)][["game_id", "team_id", "player_id"]].merge(sched, on="game_id", how="left")
    act["player_id"] = act["player_id"].astype("int64")
    a = _lookup(act, st)
    a[cols] = a[cols].fillna(0.0)
    a = a.set_index(["game_id", "team_id"])[cols].add_prefix("leaky_form_")
    return exp.join(a, how="outer").reset_index()


def team_form(games: pd.DataFrame, cfg: dict[str, Any], lineage: dict[int, int]) -> pd.DataFrame:
    """Per (game_id, team_id): recent win rate and current streak from the franchise's earlier games."""
    g = games[["game_id", "start_time_utc", "home_team_id", "away_team_id", "home_win"]]
    sides = pd.concat([
        g.assign(team_id=g["home_team_id"], won=g["home_win"]),
        g.assign(team_id=g["away_team_id"], won=1 - g["home_win"]),
    ])[["game_id", "team_id", "start_time_utc", "won"]]
    sides["won"] = sides["won"].astype(float)  # NaN for games not played yet
    sides["franchise_id"] = franchise_ids(sides["team_id"], lineage)
    sides = sides.sort_values(["franchise_id", "start_time_utc"]).reset_index(drop=True)
    grp = sides.groupby("franchise_id", sort=False)
    prev = grp["won"].shift(1)  # row G -> result of the franchise's previous game
    out = sides[["game_id", "team_id"]].copy()
    for w in cfg["windows"]:
        out[f"form_win_l{w}"] = prev.groupby(sides["franchise_id"]).transform(
            lambda s: s.rolling(w, min_periods=1).mean()) - 0.5
    streak = np.zeros(len(sides))
    for _, idx in grp.indices.items():
        run = 0
        for i in idx:  # value before game i, then update with game i's result
            streak[i] = run
            r = sides.at[i, "won"]
            if np.isnan(r):
                continue
            run = (max(run, 0) + 1) if r == 1 else (min(run, 0) - 1)
    out["form_streak"] = np.clip(streak, -5, 5)
    return out.fillna({c: 0.0 for c in out.columns if c.startswith("form_win")})
