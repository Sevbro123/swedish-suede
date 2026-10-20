"""Score and venue adjustment of 5v5 shot attempts and xG.

Score effects: a trailing team takes more of the shots (the leader sits back), so raw shot shares
partly measure game state rather than team quality. Each shot is weighted by how unusual its
share is for the shooting team's state (lead clipped to +-``score_cap``, home or away),
following McCurdy's method:

    s(d, h)  = this state's share of 5v5 events = F(d, h) / (F(d, h) + F(-d, not h))
    s_bar(h) = overall share for home (or away) teams
    weight   = s_bar(h) / s(d, h)

F(d, h) is the league total of the stat for teams in state (d, h); the opponent of a team in state
(d, h) is in state (-d, not h), so a team's against-events get the opponent's weight.

Venue effects: scorekeepers at some arenas record more (or fewer) attempts, and shot locations
differently, which moves xG too. A venue's factor is the ratio of 5v5 event rates (both teams, per
hour of 5v5) in its home team's home games to that team's road games, divided by the league
geometric mean of that ratio, and shrunk toward 1 with ``venue_pseudo_games``. Both teams' counts
in a game at that venue are divided by the factor. Venue = home team id: an arena move within a
team (e.g. NYI 2015) keeps the old factor until the window rolls over. Neutral-site games get
factor 1 and are not used to estimate any factor.

As-of rule: coefficients used for season S come only from the seasons before S (``score_seasons``
and ``venue_seasons`` of them). The first season has no history, so its weights are 1 (it is
burn-in and never evaluated).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

STATS = ("corsi_5v5", "fenwick_5v5", "xg_5v5")


def lead_before(ev: pd.DataFrame) -> pd.Series:
    """Event team's goal lead just before each event (a goal's own state excludes that goal)."""
    e = ev.sort_values(["game_id", "sort_order"])
    goal = e["type"] == "goal"
    home = e["is_home_event"].astype("boolean").fillna(False).astype(bool)
    hg = (goal & home).astype(int).groupby(e["game_id"]).cumsum() - (goal & home).astype(int)
    ag = (goal & ~home).astype(int).groupby(e["game_id"]).cumsum() - (goal & ~home).astype(int)
    lead = np.where(home, hg - ag, ag - hg)
    return pd.Series(lead, index=e.index).reindex(ev.index)


def _prior_window(seasons: list[int], s: int, n: int) -> list[int]:
    i = seasons.index(s)
    return seasons[max(0, i - n):i]


def score_weights(shots: pd.DataFrame, stats: list[str], n_seasons: int) -> pd.DataFrame:
    """Weight per (season, lead, is_home) and stat, from the ``n_seasons`` seasons before each season.

    ``shots`` has season, lead (already clipped), is_home and one column per stat (per-event values).
    """
    tot = shots.groupby(["season", "lead", "is_home"])[stats].sum()
    seasons = sorted(shots["season"].unique())
    leads = sorted(shots["lead"].unique())
    out = []
    for s in seasons:
        idx = pd.MultiIndex.from_product([[s], leads, [False, True]], names=["season", "lead", "is_home"])
        w = pd.DataFrame(1.0, index=idx, columns=stats)
        prior = _prior_window(seasons, s, n_seasons)
        if prior:
            f = tot.loc[prior].groupby(["lead", "is_home"]).sum()
            for d in leads:
                for h in (False, True):
                    own, opp = f.loc[(d, h)], f.loc[(-d, not h)]
                    share = own / (own + opp)
                    hs = f.xs(h, level="is_home").sum()
                    s_bar = hs / (hs + f.xs(not h, level="is_home").sum())
                    w.loc[(s, d, h)] = (s_bar / share).to_numpy()
        out.append(w.where(np.isfinite(w), 1.0))  # stat absent from the window (xG before 2011-12)
    return pd.concat(out)


def venue_factors(tg: pd.DataFrame, stats: list[str], n_seasons: int, pseudo_games: float) -> pd.DataFrame:
    """Factor per (season, venue team id) and stat; > 1 means the venue records more events.

    ``tg`` is the team-game table with ``{stat}_for``/``_against``, ``toi_5v5_s``, ``is_home``,
    ``neutral_site``. Factors are estimated from the ``n_seasons`` seasons before each season.
    """
    g = tg[~tg["neutral_site"].astype(bool) & (tg["toi_5v5_s"] > 0)]
    tot = pd.DataFrame({c: g[f"{c}_for"] + g[f"{c}_against"] for c in stats})
    # time and game counts only where the stat exists, so a season without xG doesn't dilute xG rates
    has = tot.notna()
    for c in stats:
        tot[f"toi_{c}"] = g["toi_5v5_s"].where(has[c])
        tot[f"n_{c}"] = has[c].astype(int)
    tot[["season", "team_id", "is_home"]] = g[["season", "team_id", "is_home"]]
    sums = tot.groupby(["season", "team_id", "is_home"]).sum()
    seasons = sorted(tg["season"].unique())
    out = []
    for s in seasons:
        teams = sorted(tg.loc[tg["season"] == s, "team_id"].unique())
        f = pd.DataFrame(1.0, index=pd.MultiIndex.from_product([[s], teams], names=["season", "team_id"]),
                         columns=stats)
        prior = _prior_window(seasons, s, n_seasons)
        if prior:
            p = sums.loc[prior].groupby(["team_id", "is_home"]).sum()
            for c in stats:
                rate = p[c] / p[f"toi_{c}"].where(p[f"toi_{c}"] > 0)
                home, road = rate.xs(True, level="is_home"), rate.xs(False, level="is_home")
                log_r = np.log(home / road.reindex(home.index)).dropna()
                if log_r.empty:
                    continue
                log_r = log_r - log_r.mean()  # relative to the league (geometric mean of ratios = 1)
                n_home = p[f"n_{c}"].xs(True, level="is_home").reindex(log_r.index)
                shrunk = np.exp(log_r * n_home / (n_home + pseudo_games))
                hit = [t for t in teams if t in shrunk.index]
                f.loc[[(s, t) for t in hit], c] = shrunk.loc[hit].to_numpy()
        out.append(f)
    return pd.concat(out)


def adjusted_counts(ev: pd.DataFrame, cols: pd.DataFrame, tg: pd.DataFrame, games: pd.DataFrame,
                    cfg: dict[str, Any]) -> pd.DataFrame:
    """Per (game_id, team_id): ``{stat}_sa_{for,against}`` (score) and ``{stat}_sva_*`` (score + venue).

    ``ev`` are the events behind ``cols`` (same index); ``cols`` holds per-event stat values
    (``corsi_5v5`` etc.) and ``team_id``; ``tg`` is the unadjusted team-game table.
    """
    stats = [c for c in STATS if c in cols.columns]
    meta = games.set_index("game_id")[["season", "home_team_id", "neutral_site"]]
    shots = cols[["game_id", "team_id", *stats]].copy()
    shots["season"] = shots["game_id"].map(meta["season"])
    shots["is_home"] = shots["team_id"].to_numpy() == shots["game_id"].map(meta["home_team_id"]).to_numpy()
    cap = cfg["score_cap"]
    shots["lead"] = lead_before(ev).clip(-cap, cap).to_numpy()

    w = score_weights(shots, stats, cfg["score_seasons"])
    wv = w.reindex(pd.MultiIndex.from_frame(shots[["season", "lead", "is_home"]])).to_numpy()
    sa = shots[stats] * wv
    sa[["game_id", "team_id"]] = shots[["game_id", "team_id"]]
    own = sa.groupby(["game_id", "team_id"])[stats].sum()

    t = tg[["game_id", "team_id", "opp_id", "season", "is_home", "toi_5v5_s"]].copy()
    t["neutral_site"] = t["game_id"].map(meta["neutral_site"]).astype(bool).to_numpy()
    for side, key in (("for", "team_id"), ("against", "opp_id")):
        part = own.rename(columns={c: f"{c}_{side}" for c in stats})
        t = t.merge(part, left_on=["game_id", key], right_index=True, how="left")
    sa_cols = [f"{c}_{side}" for c in stats for side in ("for", "against")]
    t[sa_cols] = t[sa_cols].fillna(0.0)
    if "xg_5v5" in stats:  # keep "no xG in this game" (burn-in) as missing, like the raw table
        miss = tg["xg_5v5_for"].isna().to_numpy()
        t.loc[miss, ["xg_5v5_for", "xg_5v5_against"]] = np.nan

    vf = venue_factors(t, stats, cfg["venue_seasons"], cfg["venue_pseudo_games"])
    venue = np.where(t["is_home"], t["team_id"], t["opp_id"])
    fv = vf.reindex(pd.MultiIndex.from_arrays([t["season"], venue])).to_numpy(dtype=float, copy=True)
    fv[t["neutral_site"].to_numpy()] = 1.0

    out = t[["game_id", "team_id"]].copy()
    for i, c in enumerate(stats):
        for side in ("for", "against"):
            out[f"{c}_sa_{side}"] = t[f"{c}_{side}"].to_numpy()
            out[f"{c}_sva_{side}"] = t[f"{c}_{side}"].to_numpy() / fv[:, i]
    return out
