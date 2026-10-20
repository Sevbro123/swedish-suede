"""Player 5v5 on-ice metrics and lineup-based team features (quick version of
``docs/player_ratings_spec.md``: no teammate or opponent adjustment yet).

Per skater-game, from shift charts and play-by-play:
- ``toi5``: 5v5 seconds on ice. A situation code holds from one event until the next, as in
  ``team_games.py``.
- ``on_xgf`` / ``on_xga``: xG of 5v5 unblocked shots for / against the player's team while they
  were on ice. A shot at second t counts for shifts with start < t <= end, so a shot at a change
  goes to the players whose shift ends then.
- ``off_xgf`` / ``off_xga``: the team's 5v5 xG with the player off the ice.

Player state after each game: exponentially decayed sums over the player's games (``halflife_games``,
across seasons and teams), giving
- ``on_xg_share`` = (F + k) / (F + A + 2k), shrunk toward 0.5 with k = ``pseudo_xg``
- ``rel_xg_share`` = on-ice share shrunk toward the off-ice share, minus the off-ice share
  (how much better the team does with this player on; 0 for a player with no history)
- ``exp_toi`` = decayed mean 5v5 TOI per game (``toi_halflife_games``)

Team features for game G, two lineup variants (the goalie pattern):
- projected (deployable): the skaters who dressed in the franchise's previous game
- ``leaky_`` actual: G's own roster (no historical as-of source for lineups, so upper bound only)
Each is ``lineup_on_xg_share`` and ``lineup_rel_xg_share`` (means weighted by ``exp_toi``) and
``lineup_missing_toi_share``: the expected-TOI share of the team's regulars (in at least
``regular_min`` of the previous ``regular_window`` games) not in the lineup.

As-of rule: a player's state for G is looked up strictly before G's start time, and the projected
lineup reads only earlier rosters.
"""
from __future__ import annotations

from collections import Counter, deque
from typing import Any

import numpy as np
import pandas as pd

from .asof import franchise_ids

PERIOD_S = 1200
UNBLOCKED = ["goal", "shot-on-goal", "missed-shot"]


def _gsec(period: pd.Series, t: pd.Series) -> np.ndarray:
    return ((period.astype("int64") - 1) * PERIOD_S + t.astype("int64")).to_numpy()


def player_games(events: pd.DataFrame, shifts: pd.DataFrame, xg: pd.DataFrame, rosters: pd.DataFrame,
                 bad_games: set | None = None) -> pd.DataFrame:
    """One row per (game_id, team_id, player_id) skater-game with 5v5 TOI and on/off-ice xG."""
    bad_games = bad_games or set()
    goalies = set(map(tuple, rosters.loc[rosters["position"] == "G", ["game_id", "player_id"]].to_numpy()))
    sh = shifts[~shifts["game_id"].isin(bad_games)].dropna(subset=["period", "start_s", "end_s"])
    is_g = [(g, p) in goalies for g, p in zip(sh["game_id"].to_numpy(), sh["player_id"].to_numpy())]
    sh = sh[~np.array(is_g, dtype=bool)].sort_values("game_id")

    ev = events[(events["period_type"] != "SO") & events["game_id"].isin(set(sh["game_id"]))]
    ev = ev.sort_values(["game_id", "sort_order"])
    shots = ev[ev["type"].isin(UNBLOCKED) & (ev["situation_code"] == "1551").fillna(False) & ev["event_team_id"].notna()]
    shots = shots.merge(xg[["game_id", "event_id", "xg"]], on=["game_id", "event_id"], how="left")

    def bounds(gids: np.ndarray):
        u, i = np.unique(gids, return_index=True)
        return dict(zip(u, zip(i, np.append(i[1:], len(gids)))))

    sh_g, sh_p, sh_t = (sh[c].to_numpy("int64") for c in ("game_id", "player_id", "team_id"))
    sh_s, sh_e = _gsec(sh["period"], sh["start_s"]), _gsec(sh["period"], sh["end_s"])
    ev_g, ev_t = ev["game_id"].to_numpy("int64"), _gsec(ev["period"], ev["t_period_s"])
    ev_5 = (ev["situation_code"] == "1551").fillna(False).to_numpy(bool)
    sg, st = shots["game_id"].to_numpy("int64"), _gsec(shots["period"], shots["t_period_s"])
    steam, sx = shots["event_team_id"].to_numpy("int64"), shots["xg"].fillna(0.0).to_numpy(float)
    b_sh, b_ev, b_s = bounds(sh_g), bounds(ev_g), bounds(sg)

    toi5 = np.zeros(len(sh))
    xgf = np.zeros(len(sh))
    xga = np.zeros(len(sh))
    team_rows = []
    for gid, (a, b) in b_sh.items():
        if gid not in b_ev:
            continue
        ea, eb = b_ev[gid]
        T = np.maximum.accumulate(np.clip(ev_t[ea:eb], 0, None))
        n = int(max(T.max(), sh_e[a:b].max())) + 1
        lengths = np.diff(np.append(T, n))
        state = np.concatenate([np.zeros(T[0], bool), np.repeat(ev_5[ea:eb], lengths)])
        cs = np.concatenate([[0], np.cumsum(state)])
        s0, s1 = np.clip(sh_s[a:b], 0, n), np.clip(sh_e[a:b], 0, n)
        toi5[a:b] = cs[s1] - cs[s0]
        teams = np.unique(sh_t[a:b])
        tot = {t: [0.0, 0.0] for t in teams}
        if gid in b_s:
            qa, qb = b_s[gid]
            ts, tt, x = st[qa:qb], steam[qa:qb], sx[qa:qb]
            on = (sh_s[a:b][None, :] < ts[:, None]) & (ts[:, None] <= sh_e[a:b][None, :])
            own = tt[:, None] == sh_t[a:b][None, :]
            xgf[a:b] = (on & own).T.astype(float) @ x
            xga[a:b] = (on & ~own).T.astype(float) @ x
            for t in teams:
                tot[t] = [float(x[tt == t].sum()), float(x[tt != t].sum())]
        for t in teams:
            team_rows.append((gid, t, cs[-1], *tot[t]))

    pg = pd.DataFrame({"game_id": sh_g, "team_id": sh_t, "player_id": sh_p, "toi5": toi5,
                       "on_xgf": xgf, "on_xga": xga})
    pg = pg.groupby(["game_id", "team_id", "player_id"], as_index=False).sum()
    tm = pd.DataFrame(team_rows, columns=["game_id", "team_id", "team_toi5", "team_xgf", "team_xga"])
    pg = pg.merge(tm, on=["game_id", "team_id"], how="left", validate="many_to_one")
    pg["off_xgf"] = pg["team_xgf"] - pg["on_xgf"]
    pg["off_xga"] = pg["team_xga"] - pg["on_xga"]
    return pg


def player_states(pg: pd.DataFrame, games: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Per skater-game: the player's metrics *after* that game (look them up strictly before G)."""
    p = pg.merge(games[["game_id", "start_time_utc"]], on="game_id", how="left")
    p = p.sort_values(["player_id", "start_time_utc"]).reset_index(drop=True)
    h = cfg["halflife_games"]
    lam = 0.5 ** (1 / h)
    grp = p.groupby("player_id", sort=False)
    n = grp.cumcount().to_numpy() + 1
    count = (1 - lam ** n) / (1 - lam)  # decayed number of games, so mean * count = decayed sum
    S = {c: grp[c].transform(lambda s: s.ewm(halflife=h).mean()).to_numpy() * count
         for c in ("on_xgf", "on_xga", "off_xgf", "off_xga")}
    k = cfg["pseudo_xg"]
    off_tot = S["off_xgf"] + S["off_xga"]
    off = np.where(off_tot > 0, S["off_xgf"] / np.where(off_tot > 0, off_tot, 1), 0.5)
    on_tot = S["on_xgf"] + S["on_xga"]
    out = p[["player_id", "game_id", "start_time_utc"]].copy()
    out["on_xg_share"] = (S["on_xgf"] + k) / (on_tot + 2 * k)
    out["rel_xg_share"] = (S["on_xgf"] + 2 * k * off) / (on_tot + 2 * k) - off
    out["exp_toi"] = grp["toi5"].transform(lambda s: s.ewm(halflife=cfg["toi_halflife_games"]).mean())
    return out


def _lookup(queries: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame:
    """Each query (player_id, start_time_utc) gets the player's state from strictly earlier games."""
    q = queries.sort_values("start_time_utc")
    s = states.drop(columns=["game_id"]).rename(columns={"start_time_utc": "state_time"}).sort_values("state_time")
    m = pd.merge_asof(q, s, left_on="start_time_utc", right_on="state_time", by="player_id",
                      allow_exact_matches=False, direction="backward")
    return m.drop(columns=["state_time"])


def lineup_features(rosters: pd.DataFrame, games: pd.DataFrame, states: pd.DataFrame,
                    cfg: dict[str, Any], lineage: dict[int, int]) -> pd.DataFrame:
    """Per (game_id, team_id): projected and ``leaky_`` actual lineup features."""
    sk = rosters[rosters["position"] != "G"]
    roster = {k: list(v) for k, v in sk.groupby(["game_id", "team_id"])["player_id"]}
    g = games[["game_id", "start_time_utc", "home_team_id", "away_team_id"]]
    sides = pd.concat([g.assign(team_id=g["home_team_id"]), g.assign(team_id=g["away_team_id"])])
    sides = sides[["game_id", "team_id", "start_time_utc"]]
    sides["franchise_id"] = franchise_ids(sides["team_id"], lineage)
    sides = sides.sort_values(["franchise_id", "start_time_utc"])

    win, need = cfg["regular_window"], cfg["regular_min"]
    rows = []  # (game_id, team_id, start, player_id, in_projected, in_actual, is_regular)
    for _, fr in sides.groupby("franchise_id", sort=False):
        last: deque = deque(maxlen=win)
        counts: Counter = Counter()
        prev = None
        for gid, tid, t in zip(fr["game_id"], fr["team_id"], fr["start_time_utc"]):
            actual = set(roster.get((gid, tid), []))
            proj = set(prev) if prev is not None else set()
            regs = {p for p, c in counts.items() if c >= need}
            for p in proj | actual | regs:
                rows.append((gid, tid, t, p, p in proj, p in actual, p in regs))
            if actual:  # a game without a roster leaves the history as it was
                if len(last) == win:
                    counts.subtract(last[0])
                last.append(actual)
                counts.update(actual)
                prev = actual
    q = pd.DataFrame(rows, columns=["game_id", "team_id", "start_time_utc", "player_id", "proj", "actual", "regular"])
    m = _lookup(q, states)
    m["on_xg_share"] = m["on_xg_share"].fillna(0.5)
    m["rel_xg_share"] = m["rel_xg_share"].fillna(0.0)
    m["exp_toi"] = m["exp_toi"].fillna(cfg["default_toi_s"])

    out = sides[["game_id", "team_id"]].set_index(["game_id", "team_id"])
    key = ["game_id", "team_id"]
    reg_toi = m[m["regular"]].groupby(key)["exp_toi"].sum()
    for flag, prefix in (("proj", ""), ("actual", "leaky_")):
        L = m[m[flag]]
        w = L["exp_toi"]
        tot = w.groupby([L["game_id"], L["team_id"]]).sum()
        for c in ("on_xg_share", "rel_xg_share"):
            out[f"{prefix}lineup_{c}"] = (L[c] * w).groupby([L["game_id"], L["team_id"]]).sum() / tot
        miss = m[m["regular"] & ~m[flag]].groupby(key)["exp_toi"].sum()
        out[f"{prefix}lineup_missing_toi_share"] = (miss.reindex(reg_toi.index, fill_value=0) / reg_toi)
    return out.reset_index()
