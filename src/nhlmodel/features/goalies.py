"""Goalie quality and starting-goalie handling.

Quality = goals saved above expected (GSAx) on unblocked, non-empty-net shots the goalie faced:
sum(xG) - goals, expressed per 100 shots. A goalie's rating as of game G is his state after his
last game that started strictly before G (an as-of join), so G and later games never contribute.

Ratings (per 100 shots, shrunk toward the league average of 0 by ``prior_shots`` pseudo-shots):
- career: all earlier games
- season: earlier games this season (0 shots -> 0, i.e. the prior)
- ewm: exponentially weighted (halflife in games) GSAx / shots, shrunk by career shot volume

Two ways to attach a goalie to game G (both reported; see README):
- ``actual``: the goalie who actually started (post-game ``starter`` flag). LEAKY upper bound:
  at prediction time the starter is often unconfirmed, and the market reacts to confirmations.
- ``projected`` / ``expected``: a pre-game starter model (``starter_probabilities``) fit only on
  earlier seasons gives P(start) for each recent goalie; ``projected`` uses the most likely one,
  ``expected`` averages ratings weighted by P(start). A frequency rule was tried first and was
  worse: NHL teams often alternate goalies (Boston 2023-24 strictly alternated), and teams
  repeat the previous game's starter only ~42% of the time.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

RATING_COLS = ["gsax100_career", "gsax100_season", "gsax100_ewm", "shots_career"]


def goalie_games_with_xg(shots_xg: pd.DataFrame, goalie_games: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Per goalie-game: xGA, GA and shots faced (unblocked, non-empty-net), with start time and starter flag.

    ``shots_xg``: shot rows with game_id, goalie_id, goal, xg, empty_net.
    """
    s = shots_xg[(shots_xg["empty_net"] == 0) & shots_xg["goalie_id"].notna()]
    faced = s.groupby(["game_id", "goalie_id"]).agg(xga=("xg", "sum"), ga=("goal", "sum"), shots=("xg", "size"))
    faced.index = faced.index.set_names(["game_id", "player_id"])
    gg = goalie_games.merge(faced.reset_index(), on=["game_id", "player_id"], how="left")
    gg[["xga", "ga", "shots"]] = gg[["xga", "ga", "shots"]].fillna(0)
    gg = gg.merge(games[["game_id", "season", "start_time_utc"]], on="game_id", how="left")
    return gg.sort_values(["player_id", "start_time_utc"]).reset_index(drop=True)


def league_offset(gg: pd.DataFrame, prior_shots: float) -> pd.Series:
    """Per goalie-game: league-average GSAx per shot from games that started strictly earlier.

    xG drifts between seasons (e.g. it ran 5-6% high in recent seasons), which would make every
    goalie look above average that season. Subtracting this offset makes GSAx league-relative.
    Within a season, the running league rate is blended with ``prior_shots`` pseudo-shots at the
    previous season's full rate (0 for the first season).
    """
    d = gg[["season", "start_time_utc", "xga", "ga", "shots"]].astype({"xga": float, "ga": float, "shots": float})
    d = d.assign(g=d["xga"] - d["ga"]).sort_values("start_time_utc")
    prev_rate = d.groupby("season").apply(lambda x: x["g"].sum() / max(x["shots"].sum(), 1), include_groups=False)
    prev_rate = prev_rate.shift(1).fillna(0.0)
    out = pd.Series(0.0, index=d.index)
    for season, x in d.groupby("season", sort=False):
        t = x["start_time_utc"].to_numpy()
        cg, cs = x["g"].cumsum().to_numpy(), x["shots"].cumsum().to_numpy()
        idx = np.searchsorted(t, t, side="left") - 1  # last row that started strictly earlier
        g_before = np.where(idx >= 0, cg[np.maximum(idx, 0)], 0.0)
        s_before = np.where(idx >= 0, cs[np.maximum(idx, 0)], 0.0)
        m = prev_rate.get(season, 0.0)
        out.loc[x.index] = (g_before + prior_shots * m) / (s_before + prior_shots)
    return out.reindex(gg.index)


def post_game_state(gg: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Each goalie's cumulative state *after* each of his games (includes that game)."""
    gsax = gg["xga"] - gg["ga"]
    if cfg.get("league_relative", True):
        gsax = gsax - gg["shots"] * league_offset(gg, cfg.get("league_prior_shots", 5000))
    p = gg["player_id"]
    st = gg[["player_id", "season", "start_time_utc"]].copy()
    st["cum_gsax"] = gsax.groupby(p).cumsum()
    st["cum_shots"] = gg["shots"].groupby(p).cumsum()
    st["season_gsax"] = gsax.groupby([p, gg["season"]]).cumsum()
    st["season_shots"] = gg["shots"].groupby([p, gg["season"]]).cumsum()
    h = cfg["ewm_halflife_games"]
    st["ewm_gsax"] = gsax.groupby(p).transform(lambda x: x.ewm(halflife=h).mean())
    st["ewm_shots"] = gg["shots"].groupby(p).transform(lambda x: x.ewm(halflife=h).mean())
    return st


def ratings_asof(state: pd.DataFrame, queries: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Ratings for (player_id, start_time_utc, season) queries from the state strictly before that time."""
    k = cfg["prior_shots"]
    q = queries.reset_index(names="_row").dropna(subset=["player_id"]).copy()
    q["player_id"] = q["player_id"].astype("int64")
    s = state.copy()
    s["player_id"] = s["player_id"].astype("int64")
    s = s.rename(columns={"season": "state_season"})
    m = pd.merge_asof(
        q.sort_values("start_time_utc"), s.sort_values("start_time_utc"),
        on="start_time_utc", by="player_id", allow_exact_matches=False, direction="backward",
    )
    shots = m["cum_shots"].fillna(0)
    out = pd.DataFrame(index=m["_row"])
    out["shots_career"] = shots.to_numpy()
    out["gsax100_career"] = (100 * m["cum_gsax"].fillna(0) / (shots + k)).to_numpy()
    same = (m["state_season"] == m["season"]).to_numpy()
    s_g = np.where(same, m["season_gsax"].fillna(0), 0.0)
    s_s = np.where(same, m["season_shots"].fillna(0), 0.0)
    out["gsax100_season"] = 100 * s_g / (s_s + k)
    rate = (m["ewm_gsax"] / m["ewm_shots"].where(m["ewm_shots"] > 0)).fillna(0)
    out["gsax100_ewm"] = (100 * rate * shots / (shots + k)).to_numpy()
    return out.reindex(range(len(queries))).set_axis(queries.index)


CAND_FEATURES = ["started_prev", "streak", "share_last3", "share_last10", "days_since_start", "b2b_second",
                 "started_prev_and_b2b"]


def starter_candidates(gg: pd.DataFrame, games: pd.DataFrame, pool_games: int = 20) -> pd.DataFrame:
    """One row per (team-game, candidate goalie): pre-game features and whether he started.

    Candidates are goalies who started any of the team's previous ``pool_games`` games. Every
    feature uses only the team's earlier games. ``label`` is the post-game outcome (training only).
    """
    st = gg[gg["starter"].astype(bool)][["game_id", "team_id", "player_id"]]
    st = st.merge(games[["game_id", "season", "start_time_utc", "local_date"]], on="game_id")
    st = st.sort_values(["team_id", "start_time_utc"])
    rows = []
    for team, h in st.groupby("team_id", sort=False):
        s = h["player_id"].tolist()
        d = pd.to_datetime(h["local_date"]).tolist()
        gids, seasons = h["game_id"].tolist(), h["season"].tolist()
        for i in range(1, len(h)):
            past = s[max(0, i - pool_games):i]
            b2b = int((d[i] - d[i - 1]).days == 1)
            for c in dict.fromkeys(reversed(past)):
                streak = 0
                for p in reversed(past):
                    if p != c:
                        break
                    streak += 1
                last_idx = max(j for j in range(i) if s[j] == c)
                rows.append({
                    "game_id": gids[i], "team_id": team, "season": seasons[i], "player_id": c,
                    "started_prev": int(s[i - 1] == c), "streak": min(streak, 10),
                    "share_last3": past[-3:].count(c) / len(past[-3:]),
                    "share_last10": past[-10:].count(c) / len(past[-10:]),
                    "days_since_start": min((d[i] - d[last_idx]).days, 30), "b2b_second": b2b,
                    "started_prev_and_b2b": int(s[i - 1] == c) * b2b,
                    "label": int(s[i] == c),
                })
    return pd.DataFrame(rows)


def starter_probabilities(cands: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """P(start) per candidate; season S uses a logistic model fit only on seasons < S.

    Probabilities are normalised to sum to 1 within each team-game. The first season has no
    training data and falls back to each candidate's last-10 start share.
    """
    from sklearn.linear_model import LogisticRegression

    out = []
    seasons = sorted(cands["season"].unique())
    for s in seasons:
        test = cands[cands["season"] == s].copy()
        train = cands[cands["season"] < s]
        if train.empty:
            test["p_start"] = test["share_last10"]
        else:
            m = LogisticRegression(max_iter=1000, random_state=seed).fit(train[CAND_FEATURES], train["label"])
            test["p_start"] = m.predict_proba(test[CAND_FEATURES])[:, 1]
        test["p_start"] = test["p_start"] / test.groupby(["game_id", "team_id"])["p_start"].transform("sum")
        out.append(test)
    return pd.concat(out, ignore_index=True)


def goalie_features(gg: pd.DataFrame, games: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Per team-game goalie features.

    - actual_goalie_*: rating of the goalie who actually started (LEAKY upper bound)
    - projected_goalie_*: rating of the most likely starter from the pre-game model
    - expected_goalie_*: P(start)-weighted average rating over candidates (deployable; models
      starter uncertainty instead of committing to one goalie)
    """
    state = post_game_state(gg, cfg)
    sched = games[["game_id", "season", "start_time_utc"]]

    actual = gg[gg["starter"].astype(bool)][["game_id", "team_id", "player_id"]].rename(
        columns={"player_id": "actual_goalie_id"})
    out = actual.merge(sched, on="game_id", how="left")
    q = out[["start_time_utc", "season"]].assign(player_id=out["actual_goalie_id"])
    r = ratings_asof(state, q, cfg)
    for c in RATING_COLS:
        out[f"actual_goalie_{c}"] = r[c]

    cands = starter_probabilities(starter_candidates(gg, games, cfg["candidate_pool_games"]), cfg.get("seed", 0))
    cands = cands.merge(sched.drop(columns="season"), on="game_id", how="left")
    cr = ratings_asof(state, cands[["start_time_utc", "season", "player_id"]], cfg)
    cands = pd.concat([cands, cr], axis=1)

    top = cands.loc[cands.groupby(["game_id", "team_id"])["p_start"].idxmax()]
    proj = top[["game_id", "team_id", "player_id", "p_start"] + RATING_COLS].rename(
        columns={"player_id": "projected_goalie_id", "p_start": "projected_goalie_p_start",
                 **{c: f"projected_goalie_{c}" for c in RATING_COLS}})
    w = cands[RATING_COLS].mul(cands["p_start"], axis=0)
    w[["game_id", "team_id"]] = cands[["game_id", "team_id"]]
    exp = w.groupby(["game_id", "team_id"])[RATING_COLS].sum().add_prefix("expected_goalie_").reset_index()

    out = out.merge(proj, on=["game_id", "team_id"], how="left").merge(exp, on=["game_id", "team_id"], how="left")
    out["projection_correct"] = (out["actual_goalie_id"] == out["projected_goalie_id"]).astype(float).where(
        out["projected_goalie_id"].notna())
    return out.drop(columns=["season", "start_time_utc"])
