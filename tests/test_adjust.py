"""Score and venue adjustment (features/adjust.py)."""
import numpy as np
import pandas as pd

from nhlmodel.features.adjust import lead_before, score_weights, venue_factors

S1, S2, S3 = 20202021, 20212022, 20222023


def test_lead_before_excludes_the_goal_itself():
    ev = pd.DataFrame({
        "game_id": [1, 1, 1, 1, 2],
        "sort_order": [1, 2, 3, 4, 1],
        "type": ["shot-on-goal", "goal", "goal", "missed-shot", "goal"],
        "is_home_event": [True, True, False, False, False],
    })
    # home shoots at 0-0, home scores (state before: 0), away scores trailing 0-1 (-1),
    # away shoots tied 1-1 (0); new game resets
    assert lead_before(ev).tolist() == [0, 0, -1, 0, 0]


def _shots(seed, seasons, effect):
    """Synthetic 5v5 shots: the trailing team takes ``effect`` times its normal rate."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in seasons:
        for d in (-2, -1, 0, 1, 2):
            for h in (False, True):
                base = 1000 * (1.05 if h else 1.0) * (effect if d < 0 else 1.0)
                rows += [{"season": s, "lead": d, "is_home": h, "corsi_5v5": 1.0}] * int(base + rng.integers(0, 20))
    return pd.DataFrame(rows)


def test_score_weights_use_previous_seasons_only():
    shots = _shots(0, [S1, S2, S3], effect=1.3)
    w = score_weights(shots, ["corsi_5v5"], n_seasons=1)
    assert (w.loc[S1] == 1.0).all().all()  # no history
    # trailing teams shoot more, so their events are weighted down and the leaders' up
    assert w.loc[(S2, -1, True), "corsi_5v5"] < 1 < w.loc[(S2, 1, True), "corsi_5v5"]
    # scrambling a season never changes that season's own weights
    late = shots["season"] == S2
    scr = shots.copy()
    scr.loc[late, "lead"] = np.random.default_rng(1).choice([-2, -1, 0, 1, 2], late.sum())
    w2 = score_weights(scr, ["corsi_5v5"], n_seasons=1)
    pd.testing.assert_frame_equal(w.loc[[S1, S2]], w2.loc[[S1, S2]])


def test_score_weights_equalize_each_state_to_the_overall_share():
    shots = _shots(2, [S1, S2], effect=1.4)
    w = score_weights(shots, ["corsi_5v5"], n_seasons=1).loc[S2, "corsi_5v5"]
    F = shots[shots["season"] == S1].groupby(["lead", "is_home"])["corsi_5v5"].sum()
    s_bar = F.xs(True, level="is_home").sum() / F.sum()
    for d in (-2, -1, 0, 1, 2):
        own, opp = F[(d, True)] * w[(d, True)], F[(-d, False)] * w[(-d, False)]
        assert abs(own / (own + opp) - s_bar) < 1e-12


def _team_games(seed, inflate):
    """Six teams; scorekeepers at team 1's arena record ``inflate`` times the events."""
    rng = np.random.default_rng(seed)
    rows, gid = [], 0
    for s in (S1, S2):
        for _ in range(300):
            h, a = rng.choice(np.arange(1, 7), 2, replace=False)
            gid += 1
            n = rng.poisson(90) * (inflate if h == 1 else 1.0)
            neutral = gid % 50 == 0
            for team, opp, is_home in ((h, a, True), (a, h, False)):
                rows.append({"game_id": gid, "season": s, "team_id": team, "opp_id": opp, "is_home": is_home,
                             "neutral_site": neutral, "toi_5v5_s": 3000,
                             "corsi_5v5_for": n / 2, "corsi_5v5_against": n / 2})
    return pd.DataFrame(rows)


def test_venue_factor_finds_an_inflating_rink():
    f = venue_factors(_team_games(0, inflate=1.25), ["corsi_5v5"], n_seasons=1, pseudo_games=0)
    assert (f.loc[S1] == 1.0).all().all()  # no history
    assert 1.15 < f.loc[(S2, 1), "corsi_5v5"] < 1.35
    others = f.loc[S2].drop(index=1)["corsi_5v5"]
    assert ((others > 0.9) & (others < 1.02)).all()


def test_venue_shrinkage_pulls_toward_one():
    tg = _team_games(0, inflate=1.25)
    raw = venue_factors(tg, ["corsi_5v5"], 1, pseudo_games=0).loc[(S2, 1), "corsi_5v5"]
    shrunk = venue_factors(tg, ["corsi_5v5"], 1, pseudo_games=1000).loc[(S2, 1), "corsi_5v5"]
    assert 1 < shrunk < raw
