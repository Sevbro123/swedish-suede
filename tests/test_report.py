import json
import re

import pandas as pd
import pytest

from nhlmodel.report.build import TEMPLATE, build


def test_template_is_pure_ascii():
    # Non-ASCII glyphs render from fallback fonts with different widths and break the column grid.
    assert not re.search(r"[^\x00-\x7F]", TEMPLATE.read_text())


def test_build_embeds_real_payload(tmp_path):
    from nhlmodel.config import load_config, repo_path

    if not (repo_path("data/processed/games.parquet")).exists():
        pytest.skip("games table not present")
    html = build(load_config("configs/data.yaml"), tmp_path).read_text()
    blob = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S).group(1)
    payload = json.loads(blob.replace("<\\/", "</"))
    games = pd.read_parquet(repo_path("data/processed/games.parquet"))
    assert payload["data"]["total_games"] == len(games)
    assert "/*__DATA__*/" not in html


def test_team_palettes_cover_the_32_teams():
    rows = re.findall(r'\["([A-Z]{3})", "[^"]+", \[((?:"#[0-9A-Fa-f]{6}",? ?)+)\]\]', TEMPLATE.read_text())
    assert len(rows) == 32 and len({ab for ab, _ in rows}) == 32


def test_run_info_names_and_kinds():
    from nhlmodel.report.build import run_info

    assert run_info("baseline_b")["kind"] == "main"
    assert run_info("lu_b_leaky")["kind"] == "upper"
    assert run_info("baseline_b_leaky_actual")["kind"] == "upper"
    tuned = run_info("p3_logreg_C0.1")
    assert tuned["kind"] == "detail" and "p3_logreg_C0.1" in tuned["name"]


def test_explain_groups_and_ranks_terms():
    import numpy as np

    from nhlmodel.report.build import explain, term_label

    assert term_label("d_l10_xg_5v5_share") == ("Shot quality (xG)", "5-on-5 xG share, last 10 games", "pct")
    assert term_label("d_std_pp_goals_for_per60")[0] == "Special teams"
    assert term_label("d_expected_goalie_gsax100_ewm")[0] == "Goaltending"
    terms = pd.DataFrame({"term": ["intercept", "home_games_played_season", "d_l5_xg_share", "d_ewm5_xg_share",
                                   "d_expected_goalie_gsax100_ewm", "d_rest_days"],
                          "logit": [0.15, 0.0, 0.3, 0.1, -0.5, 0.0], "home": np.nan, "away": np.nan})
    p = float(1 / (1 + np.exp(-terms["logit"].sum())))
    why = explain(terms, p, top=2)
    assert why["base"] == round(float(1 / (1 + np.exp(-0.15))), 4) and why["n_inputs"] == 4
    assert [g["name"] for g in why["groups"]] == ["Goaltending", "Shot quality (xG)", "Rest and schedule"]
    assert why["groups"][0]["pts"] < 0 < why["groups"][1]["pts"] and why["groups"][2]["pts"] == 0
    assert [t["group"] for t in why["top"]] == ["Goaltending", "Shot quality (xG)"]
    assert explain(terms, p + 0.05) is None  # terms that don't reproduce the prediction are not shown
