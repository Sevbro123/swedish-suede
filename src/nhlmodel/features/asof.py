"""As-of team features: everything for game G uses only games that started strictly before G.

How leakage is prevented structurally:
1. Feature code never sees outcomes of G: ``SCHEDULE_COLS`` is the only part of the games
   table it receives, and per-game stats come from ``team_games``.
2. Every per-team aggregate is computed on that team's history *shifted by one game*, so row G
   holds aggregates over games before G only. A team never has two games at the same start time,
   so "earlier in the team's history" == "started strictly before G".
3. League-wide quantities (shrinkage priors) use only team-games with start time < G's start time.
``tests/test_leakage.py`` checks the guarantee by scrambling all data from G onward and asserting
that G's features don't change.
"""
from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

SCHEDULE_COLS = ["game_id", "season", "start_time_utc", "local_date", "venue_timezone", "neutral_site",
                 "home_team_id", "away_team_id"]


def franchise_ids(team_ids: pd.Series, lineage: dict[int, int]) -> pd.Series:
    def root(t: int) -> int:
        seen = set()
        while t in lineage and t not in seen:
            seen.add(t)
            t = lineage[t]
        return t

    return team_ids.map(lambda t: root(int(t)))


def _league_asof(tg: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Per row: league mean per team-game of ``cols`` over team-games that started strictly earlier."""
    order = tg.sort_values("start_time_utc")
    cums = order[cols].cumsum()
    n = np.arange(1, len(order) + 1)
    t = order["start_time_utc"].to_numpy()
    # index of the last row with start time < this row's start time
    idx = np.searchsorted(t, t, side="left") - 1
    out = np.full((len(order), len(cols)), np.nan)
    ok = idx >= 0
    out[ok] = cums.to_numpy()[idx[ok]] / n[idx[ok]][:, None]
    return pd.DataFrame(out, index=order.index, columns=cols).reindex(tg.index)


def _previous_season_prior(tg: pd.DataFrame, cols: list[str], regress: float) -> pd.DataFrame:
    """Previous-season per-game rates by franchise, regressed toward that season's league mean."""
    per_team = tg.groupby(["franchise_id", "season"])[cols].mean()
    league = tg.groupby("season")[cols].mean()
    shrunk = league.reindex(per_team.index.get_level_values("season")).set_axis(per_team.index)
    shrunk = shrunk + regress * (per_team - shrunk)
    shrunk = shrunk.reset_index()
    shrunk["season"] = shrunk["season"] + 10001  # 20232024 -> 20242025: used for the NEXT season
    keyed = tg[["franchise_id", "season"]].merge(shrunk, on=["franchise_id", "season"], how="left")
    return keyed[cols].set_axis(tg.index)


def team_strength(team_games: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Per (game_id, team_id) row: windowed aggregates over that franchise's earlier games."""
    tg = team_games.copy()
    tg["franchise_id"] = franchise_ids(tg["team_id"], cfg.get("lineage", {}))
    if tg.duplicated(["franchise_id", "start_time_utc"]).any():
        # The leakage guarantee relies on a franchise's games having distinct start times.
        raise ValueError("a franchise has two games with the same start time")
    tg = tg.sort_values(["franchise_id", "start_time_utc"]).reset_index(drop=True)

    pairs = [(f"{s}_for", f"{s}_against") for s in cfg["share_stats"]]
    rate_cols = [c for s in cfg["rate_stats"] for c in (f"{s}_for", f"{s}_against")]
    base = sorted({c for p in pairs for c in p} | set(rate_cols))
    w = cfg["windows"]
    out = tg[["game_id", "team_id", "franchise_id", "season", "start_time_utc"]].copy()
    new: dict[str, pd.Series] = {}  # collected, then joined once (avoids frame fragmentation)

    g_fr = tg.groupby("franchise_id", sort=False)
    prev = g_fr[base].shift(1)  # row G -> stats of the franchise's previous game
    out["games_played_season"] = tg.groupby(["franchise_id", "season"]).cumcount()

    def emit(prefix: str, agg: pd.DataFrame, counts: pd.Series | None = None):
        for f, a in pairs:
            tot = agg[f] + agg[a]
            new[f"{prefix}_{f[:-4]}_share"] = (agg[f] / tot).where(tot > 0)
        div = counts if counts is not None else 1
        for c in rate_cols:
            new[f"{prefix}_{c}_pg"] = agg[c] / div

    if w.get("last_n"):
        if w.get("cross_season", True):
            keys, hist = [tg["franchise_id"]], prev
        else:  # shift within season too, so last season's final game can't enter the window
            keys = [tg["franchise_id"], tg["season"]]
            hist = tg.groupby(keys, sort=False)[base].shift(1)
        for n in w["last_n"]:
            roll = hist.groupby(keys, sort=False)
            sums = roll.transform(lambda s: s.rolling(n, min_periods=1).sum())
            cnt = roll[base[0]].transform(lambda s: s.rolling(n, min_periods=1).count())
            emit(f"l{n}", sums.where(cnt > 0), cnt)

    for h in w.get("ewm_halflife_games", []):
        ew = prev.groupby(tg["franchise_id"]).transform(lambda s: s.ewm(halflife=h, ignore_na=True).mean())
        emit(f"ewm{h}", ew)

    if w.get("season_to_date", True):
        sh = cfg["shrinkage"]
        k = sh["pseudo_games"]
        s_grp = tg.groupby(["franchise_id", "season"], sort=False)
        cum = s_grp[base].cumsum() - tg[base]  # sums over this season's earlier games
        n_prev = out["games_played_season"]
        prior = _previous_season_prior(tg, base, sh["regress_to_prior"])
        league_now = _league_asof(tg, base)
        prior = prior.fillna(league_now)
        blended = cum + k * prior
        emit("std", blended, n_prev + k)
        new["std_raw_corsi_5v5_share"] = (cum["corsi_5v5_for"] / (cum["corsi_5v5_for"] + cum["corsi_5v5_against"])).where(n_prev > 0)

    return pd.concat([out, pd.DataFrame(new)], axis=1)


def situational(sched: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Rest, back-to-backs, recent load and time-zone change, per (game_id, team_id)."""
    s = cfg["situational"]
    sides = pd.concat(
        [
            sched.assign(team_id=sched["home_team_id"], is_home=True),
            sched.assign(team_id=sched["away_team_id"], is_home=False),
        ]
    )
    sides["franchise_id"] = franchise_ids(sides["team_id"], cfg.get("lineage", {}))
    sides = sides.sort_values(["franchise_id", "start_time_utc"]).reset_index(drop=True)
    d = pd.to_datetime(sides["local_date"])
    g = sides.groupby("franchise_id", sort=False)
    rest = (d - g["local_date"].shift(1).pipe(pd.to_datetime)).dt.days
    first_of_season = sides["season"] != g["season"].shift(1)
    out = sides[["game_id", "team_id"]].copy()
    out["rest_days"] = rest.where(~first_of_season).clip(upper=s["rest_days_cap"]).fillna(s["rest_days_cap"])
    out["back_to_back"] = (out["rest_days"] == 1).astype(int)
    out["season_opener"] = first_of_season.astype(int)

    # games in the previous `recent_days` days (excluding today)
    def recent(group: pd.DataFrame) -> pd.Series:
        dd = pd.to_datetime(group["local_date"]).to_numpy()
        lo = np.searchsorted(dd, dd - np.timedelta64(s["recent_days"], "D"), side="left")
        return pd.Series(np.arange(len(dd)) - lo, index=group.index)

    out[f"games_last_{s['recent_days']}d"] = g[["local_date"]].apply(recent).reset_index(level=0, drop=True)

    def offset_h(tz: str, ts: pd.Timestamp) -> float:
        return ts.tz_convert(ZoneInfo(tz)).utcoffset().total_seconds() / 3600

    cur = [offset_h(tz, t) for tz, t in zip(sides["venue_timezone"], sides["start_time_utc"])]
    prev_tz = g["venue_timezone"].shift(1)
    prev_off = [np.nan if not isinstance(tz, str) else offset_h(tz, t) for tz, t in zip(prev_tz, sides["start_time_utc"])]
    out["tz_change_h"] = (np.array(cur) - np.array(prev_off))
    out.loc[first_of_season.to_numpy(), "tz_change_h"] = 0.0
    return out


def build_features(games: pd.DataFrame, team_games: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """One row per game: home_* and away_* features. Outcomes of the game are never read."""
    sched = games[SCHEDULE_COLS].copy()
    per_team = team_strength(team_games, cfg).drop(columns=["franchise_id", "season", "start_time_utc"])
    per_team = per_team.merge(situational(sched, cfg), on=["game_id", "team_id"], how="left")
    feat_cols = [c for c in per_team.columns if c not in ("game_id", "team_id")]

    out = sched[["game_id", "season", "start_time_utc", "neutral_site", "home_team_id", "away_team_id"]].copy()
    for side in ("home", "away"):
        side_feats = per_team.rename(columns={c: f"{side}_{c}" for c in feat_cols})
        out = out.merge(side_feats, left_on=["game_id", f"{side}_team_id"], right_on=["game_id", "team_id"],
                        how="left").drop(columns=["team_id"])
    return out
