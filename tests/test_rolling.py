"""Rolling re-selection (eval/rolling.py): picks for season S read only seasons before S."""
import pandas as pd

from nhlmodel.eval.rolling import candidate_configs, pick


def _losses():
    # candidate "a" is better through 2014-15, "b" from 2015-16 on
    rows = []
    for s in (20122013, 20132014, 20142015, 20152016, 20162017):
        late = s >= 20152016
        rows += [{"season": s, "a": 0.70 if late else 0.60, "b": 0.60 if late else 0.70}] * 10
    return pd.DataFrame(rows)


def test_pick_ignores_the_season_itself_and_later():
    L = _losses()
    eligible = sorted(L["season"].unique())
    assert pick(L, 20152016, None, eligible) == "a"   # 2015-16 is "b"'s season, but not visible yet
    assert pick(L, 20172018, 1, eligible) == "b"      # last season only
    assert pick(L, 20172018, None, eligible) == "a"   # 3 seasons of "a" outweigh 2 of "b"


def test_candidate_configs_cover_every_setting():
    cfg = {"candidates": {"simple": {"groups": ["xg_share"], "C": [0.01, 0.1]},
                          "full": {"features": "full", "C": [0.001]}}}
    c = candidate_configs(cfg)
    assert set(c) == {"simple_C0.01", "simple_C0.1", "full_C0.001"}
    assert c["full_C0.001"]["params"]["C"] == 0.001 and c["simple_C0.1"]["C"] == 0.1
